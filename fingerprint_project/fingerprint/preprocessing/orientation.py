"""
Orientation Normalization Module
────────────────────────────────
Corrects fingerprint rotation by estimating dominant ridge
orientation and rotating to canonical alignment.
"""

import cv2
import numpy as np
import logging

logger = logging.getLogger('fingerprint')


def normalize_orientation(image):
    """
    Normalize fingerprint orientation by estimating dominant
    ridge direction and correcting rotation.

    Args:
        image: numpy array (grayscale)

    Returns:
        numpy array: Rotation-corrected image
    """
    # ── Compute gradient field ──
    sobelx = cv2.Sobel(image.astype(np.float64), cv2.CV_64F, 1, 0, ksize=3)
    sobely = cv2.Sobel(image.astype(np.float64), cv2.CV_64F, 0, 1, ksize=3)

    # ── Ridge orientation estimation ──
    # Using gradient-based method
    block_size = 16
    h, w = image.shape[:2]
    orientations = []

    for y in range(0, h - block_size, block_size):
        for x in range(0, w - block_size, block_size):
            gx = sobelx[y:y + block_size, x:x + block_size]
            gy = sobely[y:y + block_size, x:x + block_size]

            # Compute local orientation
            vx = 2 * np.sum(gx * gy)
            vy = np.sum(gx ** 2 - gy ** 2)

            if abs(vx) > 1e-6 or abs(vy) > 1e-6:
                theta = 0.5 * np.arctan2(vx, vy)
                # Weight by gradient magnitude
                magnitude = np.sqrt(vx ** 2 + vy ** 2)
                orientations.append((theta, magnitude))

    if not orientations:
        logger.warning("Could not estimate orientation, returning original")
        return image

    # ── Find dominant orientation ──
    angles = np.array([o[0] for o in orientations])
    weights = np.array([o[1] for o in orientations])

    # Weighted circular mean
    sin_sum = np.sum(weights * np.sin(2 * angles))
    cos_sum = np.sum(weights * np.cos(2 * angles))
    dominant_angle = 0.5 * np.arctan2(sin_sum, cos_sum)
    dominant_degrees = np.degrees(dominant_angle)

    # ── Rotate to vertical alignment ──
    # Target: ridges should run roughly horizontal (90°)
    rotation_needed = 90 - dominant_degrees

    # Only rotate if significant misalignment (> 5°)
    if abs(rotation_needed) < 5:
        logger.info("Orientation already aligned (%.1f°)", dominant_degrees)
        return image

    # Rotate around center
    center = (w // 2, h // 2)
    rotation_matrix = cv2.getRotationMatrix2D(center, rotation_needed, 1.0)
    rotated = cv2.warpAffine(
        image, rotation_matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE
    )

    logger.info(
        "Orientation corrected: dominant=%.1f°, rotated=%.1f°",
        dominant_degrees, rotation_needed
    )

    return rotated
