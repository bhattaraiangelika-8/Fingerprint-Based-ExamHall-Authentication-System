"""
Template Extraction Module
──────────────────────────
Extracts fingerprint minutiae features from enhanced images
using skeletonization and neighborhood analysis.
"""

import cv2
import numpy as np
import hashlib
import struct
import logging

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

    def __init__(self, minutiae_list, width=512, height=512):
        self.minutiae = minutiae_list  # List[MinutiaePoint]
        self.width = width
        self.height = height

    @property
    def count(self):
        return len(self.minutiae)

    def serialize(self):
        """
        Serialize template to compact binary format.

        Format:
            Header: width(2B) + height(2B) + count(2B)
            Per minutiae: x(2B) + y(2B) + type(1B) + angle(4B) = 9 bytes
        """
        data = struct.pack('<HHH', self.width, self.height, self.count)
        for m in self.minutiae:
            data += struct.pack('<HHBf', m.x, m.y, m.type, m.angle)
        return data

    @classmethod
    def deserialize(cls, data):
        """Deserialize binary data back to FingerprintTemplate."""
        header_size = 6  # 3 × uint16
        width, height, count = struct.unpack('<HHH', data[:header_size])

        minutiae = []
        offset = header_size
        for _ in range(count):
            x, y, mtype, angle = struct.unpack('<HHBf', data[offset:offset + 9])
            minutiae.append(MinutiaePoint(x, y, mtype, angle))
            offset += 9

        return cls(minutiae, width, height)

    def compute_hash(self):
        """Compute SHA-256 hash of the template for integrity verification."""
        return hashlib.sha256(self.serialize()).hexdigest()


def extract_template(image):
    """
    Extract fingerprint template (minutiae features) from a
    preprocessed image.

    Steps:
        1. Binarize (adaptive threshold)
        2. Thin/skeletonize ridges
        3. Detect minutiae via 3×3 neighborhood
        4. Filter false minutiae
        5. Compute minutiae angles

    Args:
        image: numpy array (grayscale, preprocessed)

    Returns:
        FingerprintTemplate
    """
    h, w = image.shape[:2]

    # ── Step 1: Binarize ──
    binary = cv2.adaptiveThreshold(
        image, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 11, 2
    )

    # ── Step 2: Skeletonize ──
    skeleton = _skeletonize(binary)

    # ── Step 3: Detect minutiae ──
    minutiae = _detect_minutiae(skeleton)

    # ── Step 4: Filter false minutiae ──
    minutiae = _filter_minutiae(minutiae, w, h)

    # ── Step 5: Compute minutiae angles ──
    minutiae = _compute_angles(minutiae, skeleton)

    template = FingerprintTemplate(minutiae, w, h)

    logger.info(
        "Template extracted: %d minutiae (%d endings, %d bifurcations)",
        template.count,
        sum(1 for m in minutiae if m.type == RIDGE_ENDING),
        sum(1 for m in minutiae if m.type == BIFURCATION),
    )

    return template


def _skeletonize(binary_image):
    """
    Thin ridges to 1-pixel width using morphological skeletonization.
    """
    # Invert if ridges are white (we want ridges as foreground)
    if np.mean(binary_image) > 127:
        binary_image = cv2.bitwise_not(binary_image)

    # Convert to boolean for skimage
    try:
        from skimage.morphology import skeletonize as sk_skeletonize
        bool_img = binary_image > 0
        skeleton = sk_skeletonize(bool_img)
        return (skeleton * 255).astype(np.uint8)
    except ImportError:
        # Fallback: OpenCV thinning
        return cv2.ximgproc.thinning(binary_image) if hasattr(cv2, 'ximgproc') else binary_image


def _detect_minutiae(skeleton):
    """
    Detect minutiae points by analyzing the 3×3 neighborhood
    of each ridge pixel in the skeleton.

    - Ridge ending: pixel with exactly 1 neighbor
    - Bifurcation: pixel with exactly 3 neighbors
    """
    minutiae = []
    skel = (skeleton > 0).astype(np.uint8)
    h, w = skel.shape

    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if skel[y, x] == 0:
                continue

            # Count 8-connected neighbors
            neighbors = (
                skel[y - 1, x - 1] + skel[y - 1, x] + skel[y - 1, x + 1]
                + skel[y, x - 1] + skel[y, x + 1]
                + skel[y + 1, x - 1] + skel[y + 1, x] + skel[y + 1, x + 1]
            )

            if neighbors == 1:
                minutiae.append(MinutiaePoint(x, y, RIDGE_ENDING))
            elif neighbors == 3:
                minutiae.append(MinutiaePoint(x, y, BIFURCATION))

    return minutiae


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
    based on local ridge direction.
    """
    skel = (skeleton > 0).astype(np.float64)
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
