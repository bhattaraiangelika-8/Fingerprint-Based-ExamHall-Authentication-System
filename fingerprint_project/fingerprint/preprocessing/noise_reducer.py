"""
Noise Reduction Module
──────────────────────
Removes artifacts (pores, background noise, lighting noise)
from fingerprint images using filtering and morphological ops.
"""

import cv2
import numpy as np
import logging

logger = logging.getLogger('fingerprint')


def reduce_noise(image):
    """
    Apply noise reduction pipeline to a fingerprint image.

    Steps:
        1. Median filtering (salt-and-pepper noise)
        2. Gaussian smoothing (optional adaptive)
        3. Morphological opening (remove small artifacts)
        4. Morphological closing (fill ridge gaps)

    Args:
        image: numpy array (grayscale)

    Returns:
        numpy array: Cleaned image with clear ridge structures
    """
    # ── Step 1: Median filter ──
    # Effective for salt-and-pepper noise while preserving edges
    denoised = cv2.medianBlur(image, 3)

    # ── Step 2: Adaptive Gaussian smoothing ──
    # Light smoothing to reduce high-frequency noise
    noise_level = _estimate_noise(denoised)
    if noise_level > 15:
        # Higher noise → stronger smoothing
        denoised = cv2.GaussianBlur(denoised, (3, 3), 0.8)
        logger.info("Applied Gaussian smoothing (noise_level=%.1f)", noise_level)

    # ── Step 3: Morphological opening ──
    # Remove small isolated noise pixels
    kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    denoised = cv2.morphologyEx(denoised, cv2.MORPH_OPEN, kernel_open)

    # ── Step 4: Morphological closing ──
    # Fill small gaps in ridges
    kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    denoised = cv2.morphologyEx(denoised, cv2.MORPH_CLOSE, kernel_close)

    logger.info(
        "Noise reduction complete: noise_level=%.1f", noise_level
    )

    return denoised


def _estimate_noise(image):
    """
    Estimate noise level using Laplacian variance.
    Higher values → more noise or detail.
    """
    laplacian = cv2.Laplacian(image, cv2.CV_64F)
    return laplacian.var() ** 0.5
