"""
Fingerprint Region Detection
─────────────────────────────
Isolates the fingerprint area from a camera photo by detecting
skin regions, finding contours, and cropping the largest finger region.
"""

import cv2
import numpy as np
import logging

logger = logging.getLogger('fingerprint')


def detect_and_crop_fingerprint(image):
    """
    Detect and crop the fingerprint region from a camera image.

    Args:
        image: numpy array (BGR or grayscale)

    Returns:
        numpy array: Cropped fingerprint region (grayscale)
    """
    # Convert to grayscale if needed
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        color = image.copy()
    else:
        gray = image.copy()
        color = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

    # ── Step 1: Skin region detection ──
    hsv = cv2.cvtColor(color, cv2.COLOR_BGR2HSV)

    # Broad skin color range
    lower_skin = np.array([0, 20, 70], dtype=np.uint8)
    upper_skin = np.array([20, 255, 255], dtype=np.uint8)
    mask1 = cv2.inRange(hsv, lower_skin, upper_skin)

    lower_skin2 = np.array([170, 20, 70], dtype=np.uint8)
    upper_skin2 = np.array([180, 255, 255], dtype=np.uint8)
    mask2 = cv2.inRange(hsv, lower_skin2, upper_skin2)

    skin_mask = mask1 | mask2

    # Clean up the mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_CLOSE, kernel)
    skin_mask = cv2.morphologyEx(skin_mask, cv2.MORPH_OPEN, kernel)

    # ── Step 2: Edge detection ──
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)

    # Combine skin mask and edges
    combined = cv2.bitwise_and(skin_mask, skin_mask, mask=None)

    # ── Step 3: Find contours ──
    contours, _ = cv2.findContours(
        combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        logger.warning("No contours found, returning full image")
        return gray

    # ── Step 4: Find largest contour (finger region) ──
    largest_contour = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest_contour)

    # Reject if contour is too small (< 5% of image)
    min_area = gray.shape[0] * gray.shape[1] * 0.05
    if area < min_area:
        logger.warning("Detected region too small (%.1f%%), using full image",
                       area / (gray.shape[0] * gray.shape[1]) * 100)
        return gray

    # ── Step 5: Crop with padding ──
    x, y, w, h = cv2.boundingRect(largest_contour)
    padding = 20

    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(gray.shape[1], x + w + padding)
    y2 = min(gray.shape[0], y + h + padding)

    cropped = gray[y1:y2, x1:x2]

    logger.info(
        "Fingerprint region detected: bbox=(%d,%d,%d,%d), area=%.0f",
        x, y, w, h, area
    )

    return cropped
