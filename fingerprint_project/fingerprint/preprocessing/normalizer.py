"""
Image Normalization Module
──────────────────────────
Normalizes fingerprint images to a standard size, brightness,
and contrast for consistent processing.
"""

import cv2
import numpy as np
import logging
from django.conf import settings

logger = logging.getLogger('fingerprint')


def normalize_image(image, target_size=None):
    """
    Normalize a fingerprint image.

    Operations:
        1. Convert to grayscale if needed
        2. Resize to standard resolution (512×512)
        3. Apply CLAHE for contrast normalization
        4. Normalize intensity to [0, 255]

    Args:
        image: numpy array (grayscale or BGR)
        target_size: tuple (width, height), defaults to (512, 512)

    Returns:
        numpy array: Normalized grayscale image
    """
    if target_size is None:
        target_size = settings.FINGERPRINT['NORMALIZED_SIZE']

    # ── Convert to grayscale ──
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    # ── Resize to target ──
    resized = cv2.resize(
        gray,
        target_size,
        interpolation=cv2.INTER_CUBIC
    )

    # ── CLAHE (Contrast Limited Adaptive Histogram Equalization) ──
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(resized)

    # ── Normalize intensity to full [0, 255] range ──
    normalized = cv2.normalize(
        enhanced, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U
    )

    logger.info(
        "Image normalized: size=%s, mean=%.1f, std=%.1f",
        target_size, np.mean(normalized), np.std(normalized)
    )

    return normalized
