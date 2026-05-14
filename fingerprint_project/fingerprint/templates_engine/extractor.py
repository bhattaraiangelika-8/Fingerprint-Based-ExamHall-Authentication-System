"""
Template Extraction Module
──────────────────────────
Extracts fingerprint minutiae features from preprocessed images
using the proven crossing-number pipeline (normalization → segmentation
→ orientation → frequency → gabor → skeletonize → crossing number).

Can work in two modes:
  1. From pre-computed minutiae data (when pipeline already ran)
  2. Standalone extraction from a raw grayscale image
"""

import cv2
import numpy as np
import hashlib
import struct
import logging

from ..preprocessing.minutiae_core import (
    run_minutiae_pipeline,
    calculate_minutiaes,
)

logger = logging.getLogger('fingerprint')


# Minutiae types
RIDGE_ENDING = 1
BIFURCATION = 3


class MinutiaePoint:
    """Single minutiae feature point."""

    def __init__(self, x, y, minutiae_type, angle=0.0):
        self.x = x
        self.y = y
        self.type = minutiae_type  # 1=ending, 3=bifurcation
        self.angle = angle

    def to_tuple(self):
        return (self.x, self.y, self.type, self.angle)


class FingerprintTemplate:
    """Container for a fingerprint biometric template."""

    def __init__(self, minutiae_list, singularities_list=None,
                 width=512, height=512):
        self.minutiae = minutiae_list  # List[MinutiaePoint]
        self.singularities = singularities_list or []
        self.width = width
        self.height = height

    @property
    def count(self):
        return len(self.minutiae)

    def serialize(self):
        """
        Serialize template to compact binary format.

        Format:
            Header: width(2B) + height(2B) + count(2B) + sing_count(2B)
            Per minutiae: x(2B) + y(2B) + type(1B) + angle(4B) = 9 bytes
            Per singularity: x(2B) + y(2B) + type_code(1B) = 5 bytes
        """
        sing_count = len(self.singularities)
        data = struct.pack('<HHHH', self.width, self.height,
                           self.count, sing_count)
        for m in self.minutiae:
            data += struct.pack('<HHBf', m.x, m.y, m.type, m.angle)
        for s in self.singularities:
            type_code = {'loop': 1, 'delta': 2, 'whorl': 3}.get(
                s.get('type', ''), 0
            )
            data += struct.pack('<HHB', s.get('x', 0), s.get('y', 0),
                                type_code)
        return data

    @classmethod
    def deserialize(cls, data):
        """Deserialize binary data back to FingerprintTemplate."""
        header_size = 8  # 4 × uint16
        width, height, count, sing_count = struct.unpack(
            '<HHHH', data[:header_size]
        )

        minutiae = []
        offset = header_size
        for _ in range(count):
            x, y, mtype, angle = struct.unpack(
                '<HHBf', data[offset:offset + 9]
            )
            minutiae.append(MinutiaePoint(x, y, mtype, angle))
            offset += 9

        singularities = []
        type_map = {1: 'loop', 2: 'delta', 3: 'whorl'}
        for _ in range(sing_count):
            x, y, tcode = struct.unpack('<HHB', data[offset:offset + 5])
            singularities.append({
                'x': x, 'y': y, 'type': type_map.get(tcode, 'unknown')
            })
            offset += 5

        return cls(minutiae, singularities, width, height)

    def compute_hash(self):
        """Compute SHA-256 hash of the template for integrity verification."""
        return hashlib.sha256(self.serialize()).hexdigest()


def extract_template(image, minutiae_data=None):
    """
    Extract fingerprint template from a preprocessed image.

    If minutiae_data is provided (from pipeline), uses that directly.
    Otherwise runs the full minutiae extraction pipeline.

    Args:
        image: numpy array (grayscale, preprocessed, 512x512)
        minutiae_data: optional pre-computed dict from run_minutiae_pipeline

    Returns:
        FingerprintTemplate
    """
    h, w = image.shape[:2]

    # If pipeline data was pre-computed, use it directly
    if minutiae_data is None:
        logger.info("Running standalone minutiae extraction pipeline...")
        minutiae_data = run_minutiae_pipeline(image, block_size=16)

    raw_minutiae = minutiae_data.get('minutiae_points', [])
    raw_singularities = minutiae_data.get('singularities_points', [])

    # Convert raw minutiae dicts to MinutiaePoint objects
    minutiae = []
    for m in raw_minutiae:
        mtype = RIDGE_ENDING if m['type'] == 'ending' else BIFURCATION
        minutiae.append(MinutiaePoint(m['x'], m['y'], mtype))

    # Filter false minutiae (border artifacts and duplicates)
    minutiae = _filter_minutiae(minutiae, w, h)

    # Compute minutiae angles from the skeleton
    thin_image = minutiae_data.get('thin_image', None)
    if thin_image is not None:
        minutiae = _compute_angles(minutiae, thin_image)

    template = FingerprintTemplate(minutiae, raw_singularities, w, h)

    logger.info(
        "Template extracted: %d minutiae (%d endings, %d bifurcations), "
        "%d singularities",
        template.count,
        sum(1 for m in minutiae if m.type == RIDGE_ENDING),
        sum(1 for m in minutiae if m.type == BIFURCATION),
        len(raw_singularities),
    )

    return template


def _filter_minutiae(minutiae, width, height):
    """
    Remove false minutiae near borders and duplicates.
    """
    border = 20
    filtered = []

    for m in minutiae:
        # Skip border minutiae (often artifacts)
        if m.x < border or m.x > width - border:
            continue
        if m.y < border or m.y > height - border:
            continue

        # Skip if too close to another minutiae
        is_duplicate = False
        for existing in filtered:
            dist = np.sqrt((m.x - existing.x) ** 2 + (m.y - existing.y) ** 2)
            if dist < 10:
                is_duplicate = True
                break

        if not is_duplicate:
            filtered.append(m)

    return filtered


def _compute_angles(minutiae, skeleton):
    """
    Compute orientation angle for each minutiae point
    based on local ridge direction in the skeleton.
    """
    skel = (skeleton > 0).astype(np.float64)
    # Invert if ridges are white (skeleton from reference has ridges dark)
    if np.mean(skeleton) > 127:
        skel = 1.0 - skel
    h, w = skel.shape

    for m in minutiae:
        x, y = m.x, m.y

        # Small region around minutiae
        r = 10
        y1, y2 = max(0, y - r), min(h, y + r)
        x1, x2 = max(0, x - r), min(w, x + r)

        region = skel[y1:y2, x1:x2]

        if region.size == 0:
            m.angle = 0.0
            continue

        # Compute gradient direction
        gy, gx = np.gradient(region)
        m.angle = float(np.arctan2(np.mean(gy), np.mean(gx)))

    return minutiae
