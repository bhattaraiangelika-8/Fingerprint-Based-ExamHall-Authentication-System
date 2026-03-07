"""
Ridge Enhancement Module
─────────────────────────
Enhances fingerprint ridge structures using Gabor filtering
to improve minutiae detection accuracy.
"""

import cv2
import numpy as np
import logging

logger = logging.getLogger('fingerprint')


def enhance_ridges(image):
    """
    Enhance fingerprint ridges using Gabor filtering.

    Attempts to use the fingerprint_enhancer library first,
    falling back to a manual Gabor filter bank.

    Args:
        image: numpy array (grayscale, 8-bit)

    Returns:
        numpy array: Enhanced binary ridge image
    """
    try:
        enhanced = _enhance_with_library(image)
        logger.info("Ridge enhancement completed (library method)")
        return enhanced
    except Exception as e:
        logger.warning("Library enhancement failed: %s, using manual Gabor", e)
        enhanced = _enhance_with_gabor_bank(image)
        logger.info("Ridge enhancement completed (manual Gabor method)")
        return enhanced


def _enhance_with_library(image):
    """Use fingerprint_enhancer library for Gabor-based enhancement."""
    import fingerprint_enhancer

    # Ensure uint8 input
    if image.dtype != np.uint8:
        image = image.astype(np.uint8)

    enhanced = fingerprint_enhancer.enhance_Fingerprint(image)

    # Convert to binary
    if enhanced.dtype != np.uint8:
        enhanced = (enhanced * 255).astype(np.uint8)

    return enhanced


def _enhance_with_gabor_bank(image):
    """
    Manual Gabor filter bank for ridge enhancement.

    Applies oriented Gabor filters across 8 directions and
    combines the results for optimal ridge visibility.
    """
    # Estimate ridge frequency (typical: ~1/9 for 500dpi)
    ridge_freq = 1.0 / 9.0

    # Gabor filter parameters
    ksize = 31
    sigma = 4.0
    lambd = 1.0 / ridge_freq
    gamma = 0.5  # Aspect ratio
    psi = 0  # Phase offset

    # Apply Gabor filters at 8 orientations (0 to 7π/8)
    num_orientations = 8
    responses = []

    for i in range(num_orientations):
        theta = i * np.pi / num_orientations
        kernel = cv2.getGaborKernel(
            (ksize, ksize), sigma, theta, lambd, gamma, psi, ktype=cv2.CV_32F
        )
        kernel /= 1.5 * kernel.sum()

        filtered = cv2.filter2D(
            image.astype(np.float32), cv2.CV_32F, kernel
        )
        responses.append(filtered)

    # Take maximum response across all orientations
    combined = np.max(responses, axis=0)

    # Normalize to [0, 255]
    combined = cv2.normalize(combined, None, 0, 255, cv2.NORM_MINMAX)
    combined = combined.astype(np.uint8)

    # Binarize
    _, binary = cv2.threshold(combined, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    return binary
