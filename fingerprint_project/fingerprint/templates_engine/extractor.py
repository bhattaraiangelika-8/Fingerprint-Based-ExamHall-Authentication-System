"""
Template Extraction Module  —  v4 Integration
──────────────────────────────────────────────
Extracts FingerprintTemplate from a PreprocessingResult (v4 pipeline output).

Minutiae format from v4 pipeline:
    {'x': int, 'y': int, 'type': 'end' | 'bif', 'angle': float}

Works in two modes:
  1. From PreprocessingResult  — zero extra computation (pipeline already ran)
  2. Standalone from raw image — runs preprocess_camera_image internally
"""

import cv2
import numpy as np
import hashlib
import struct
import logging

from ..preprocessing.pipeline import (
    preprocess_camera_image,
    orientation_field,
    extract_oriented_minutiae,
    ridge_frequency_map,
)

logger = logging.getLogger('fingerprint')

# Minutiae type codes (stored in binary template)
RIDGE_ENDING   = 1
BIFURCATION    = 3


# ══════════════════════════════════════════════════════════════════
#  DATA CLASSES
# ══════════════════════════════════════════════════════════════════

class MinutiaePoint:
    """Single minutiae feature point."""

    def __init__(self, x, y, minutiae_type, angle=0.0):
        self.x     = x
        self.y     = y
        self.type  = minutiae_type   # RIDGE_ENDING=1 or BIFURCATION=3
        self.angle = angle

    def to_tuple(self):
        return (self.x, self.y, self.type, self.angle)


class FingerprintTemplate:
    """Container for a fingerprint biometric template."""

    def __init__(self, minutiae_list, singularities_list=None, width=400, height=500):
        self.minutiae       = minutiae_list        # List[MinutiaePoint]
        self.singularities  = singularities_list or []
        self.width          = width
        self.height         = height

    @property
    def count(self):
        return len(self.minutiae)

    def serialize(self):
        """
        Compact binary format:
            Header : width(2B) + height(2B) + count(2B) + sing_count(2B)
            Minutia: x(2B) + y(2B) + type(1B) + angle(4B)  = 9 bytes each
            Singul : x(2B) + y(2B) + type_code(1B)          = 5 bytes each
        """
        sing_count = len(self.singularities)
        data = struct.pack('<HHHH', self.width, self.height, self.count, sing_count)
        for m in self.minutiae:
            data += struct.pack('<HHBf', m.x, m.y, m.type, m.angle)
        for s in self.singularities:
            code = {'loop': 1, 'delta': 2, 'whorl': 3}.get(s.get('type', ''), 0)
            data += struct.pack('<HHB', s.get('x', 0), s.get('y', 0), code)
        return data

    @classmethod
    def deserialize(cls, data):
        """Deserialize binary data back to FingerprintTemplate."""
        width, height, count, sing_count = struct.unpack('<HHHH', data[:8])
        minutiae = []
        offset   = 8
        for _ in range(count):
            x, y, mtype, angle = struct.unpack('<HHBf', data[offset:offset + 9])
            minutiae.append(MinutiaePoint(x, y, mtype, angle))
            offset += 9
        type_map      = {1: 'loop', 2: 'delta', 3: 'whorl'}
        singularities = []
        for _ in range(sing_count):
            x, y, tcode = struct.unpack('<HHB', data[offset:offset + 5])
            singularities.append({'x': x, 'y': y, 'type': type_map.get(tcode, 'unknown')})
            offset += 5
        return cls(minutiae, singularities, width, height)

    def compute_hash(self):
        """SHA-256 of serialized template for integrity verification."""
        return hashlib.sha256(self.serialize()).hexdigest()


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def extract_template(image_or_result, minutiae_data=None):
    """
    Extract FingerprintTemplate from a PreprocessingResult or raw image.

    Args:
        image_or_result: PreprocessingResult  OR  numpy array (grayscale)
        minutiae_data:   ignored — kept for API compatibility

    Returns:
        FingerprintTemplate
    """
    from ..preprocessing.pipeline import PreprocessingResult

    if isinstance(image_or_result, PreprocessingResult):
        result = image_or_result
    else:
        # Standalone mode — run camera pipeline on raw grayscale image
        logger.info("extract_template: standalone mode, running camera pipeline")
        result = preprocess_camera_image(image_or_result)

    H, W = result.processed_image.shape[:2]

    # Convert v4 minutiae dicts -> MinutiaePoint objects
    raw_minutiae = result.minutiae   # [{'x','y','type':'end'|'bif','angle'}]
    minutiae     = []
    for m in raw_minutiae:
        mtype = RIDGE_ENDING if m['type'] == 'end' else BIFURCATION
        minutiae.append(MinutiaePoint(m['x'], m['y'], mtype, m.get('angle', 0.0)))

    # Apply false-minutiae filters
    minutiae = _filter_minutiae(
        minutiae, W, H,
        thin_image = result.skeleton,
        freq_map   = result.ridge_freq_map,
    )

    # Recompute angles from skeleton (redundant but ensures consistency)
    minutiae = _compute_angles(minutiae, result.skeleton)

    template = FingerprintTemplate(minutiae, [], W, H)
    logger.info(
        "Template extracted: %d minutiae (%d endings, %d bifurcations)",
        template.count,
        sum(1 for m in minutiae if m.type == RIDGE_ENDING),
        sum(1 for m in minutiae if m.type == BIFURCATION),
    )
    return template


# ══════════════════════════════════════════════════════════════════
#  FALSE-MINUTIAE FILTERS
# ══════════════════════════════════════════════════════════════════

def _ridge_width_D(freq_map):
    """
    Half inter-ridge spacing D from frequency map (clamped to [4, 15] px).
    Used by ridge-width-based false minutiae removal rules.
    """
    non_zero = freq_map[freq_map > 0]
    if len(non_zero) == 0:
        return 8
    med = float(np.median(non_zero))
    if med <= 0:
        return 8
    return max(4, min(int(0.5 / med + 0.5), 15))


def _remove_false_by_ridge_width(minutiae, thin_image, freq_map):
    """
    Remove false minutiae using inter-ridge-width rules (m1-m7):
      - Bifurcation + Termination within D  → hook/spur
      - Two bifurcations within D           → bridge/overlap
      - Two terminations within D           → broken ridge
    Both points in each offending pair are removed.
    """
    D      = _ridge_width_D(freq_map)
    binary = (thin_image < 10).astype(np.uint8)
    labels = cv2.connectedComponentsWithStats(binary, connectivity=8)[1]

    to_remove = set()
    for i in range(len(minutiae)):
        if i in to_remove:
            continue
        for j in range(i + 1, len(minutiae)):
            if j in to_remove:
                continue
            m1, m2 = minutiae[i], minutiae[j]
            if np.hypot(m1.x - m2.x, m1.y - m2.y) > D:
                continue
            x1, y1 = int(m1.x), int(m1.y)
            x2, y2 = int(m2.x), int(m2.y)
            h, w   = labels.shape
            if not (0 <= x1 < w and 0 <= y1 < h and 0 <= x2 < w and 0 <= y2 < h):
                continue
            if labels[y1, x1] == 0 or labels[y2, x2] == 0:
                continue
            if labels[y1, x1] != labels[y2, x2]:
                continue
            to_remove.update({i, j})

    return [m for idx, m in enumerate(minutiae) if idx not in to_remove]


def _filter_minutiae(minutiae, width, height, thin_image=None, freq_map=None):
    """
    Multi-stage false-minutiae removal:
      1. Border removal  (20 px margin)
      2. Ridge-width rules (m1-m7)  if skeleton + freq_map available
      3. Duplicate removal           (20 px radius)
      4. Density filter              (> 100 minutiae → keep isolated ones)
    """
    border   = 20
    filtered = [m for m in minutiae
                if border <= m.x <= width - border and border <= m.y <= height - border]

    if thin_image is not None and freq_map is not None and len(filtered) > 5:
        filtered = _remove_false_by_ridge_width(filtered, thin_image, freq_map)

    # Duplicate removal
    unique = []
    for m in filtered:
        if not any(np.hypot(m.x - e.x, m.y - e.y) < 20 for e in unique):
            unique.append(m)

    # Density filter
    if len(unique) > 100:
        densities = [
            sum(1 for j, n in enumerate(unique) if i != j and np.hypot(m.x-n.x, m.y-n.y) < 30)
            for i, m in enumerate(unique)
        ]
        keep = max(80, len(unique) // 2)
        idxs = np.argsort(densities)[:keep]
        unique = [unique[i] for i in sorted(idxs)]

    return unique


def _compute_angles(minutiae, skeleton):
    """
    Refine orientation angle for each minutia from local gradient of skeleton.
    """
    skel = (skeleton > 0).astype(np.float64)
    if np.mean(skeleton) > 127:
        skel = 1.0 - skel
    h, w = skel.shape
    for m in minutiae:
        r   = 10
        y1  = max(0, m.y - r); y2 = min(h, m.y + r)
        x1  = max(0, m.x - r); x2 = min(w, m.x + r)
        rgn = skel[y1:y2, x1:x2]
        if rgn.size == 0:
            m.angle = 0.0
            continue
        gy, gx  = np.gradient(rgn)
        m.angle = float(np.arctan2(np.mean(gy), np.mean(gx)))
    return minutiae
