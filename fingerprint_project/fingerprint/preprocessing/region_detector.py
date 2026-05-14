"""
Fingerprint Region Detection
─────────────────────────────
Isolates the fingerprint area from a camera photo using a hybrid
3-strategy approach that works for:
  - Photos of actual fingers (skin-color detection)
  - Photos of fingerprints on paper (contrast-based detection)
  - Sensor images / generic fallback (edge-density detection)
"""

import cv2
import numpy as np
import logging

logger = logging.getLogger('fingerprint')


def detect_and_crop_fingerprint(image):
    """
    Detect and crop the fingerprint region from a camera image.

    Tries three strategies in order and picks the best result:
      A) Skin-color segmentation (for real finger photos)
      B) Contrast-based thresholding (for ink-on-paper fingerprints)
      C) Edge-density detection (generic fallback)

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

    img_area = gray.shape[0] * gray.shape[1]
    min_region = img_area * 0.05  # Region must be ≥5% of image

    # ── Strategy A: Skin Color Detection ──
    crop_a, conf_a = _strategy_skin_color(gray, color, min_region)

    # ── Strategy B: Contrast-Based (ink on paper) ──
    crop_b, conf_b = _strategy_contrast(gray, min_region)

    # ── Strategy C: Edge Density Fallback ──
    crop_c, conf_c = _strategy_edge_density(gray, min_region)

    # Pick the best strategy
    candidates = [
        ('skin_color', crop_a, conf_a),
        ('contrast', crop_b, conf_b),
        ('edge_density', crop_c, conf_c),
    ]
    candidates.sort(key=lambda x: x[2], reverse=True)

    best_name, best_crop, best_conf = candidates[0]

    if best_conf > 0:
        logger.info(
            "Region detected via %s (confidence=%.2f). "
            "All scores: skin=%.2f, contrast=%.2f, edge=%.2f",
            best_name, best_conf, conf_a, conf_b, conf_c
        )
        return best_crop
    else:
        logger.warning(
            "No fingerprint region detected by any strategy, "
            "returning full image. Scores: skin=%.2f, contrast=%.2f, edge=%.2f",
            conf_a, conf_b, conf_c
        )
        return gray


# ──────────────────────────────────────────────
# Strategy A: Skin Color Detection
# ──────────────────────────────────────────────

def _strategy_skin_color(gray, color, min_region):
    """
    Detect fingerprint region via HSV skin-color segmentation.
    Best for: photos of actual fingers/thumbs.

    Returns:
        tuple: (cropped_image, confidence_score)
    """
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

    skin_ratio = np.count_nonzero(skin_mask) / skin_mask.size

    if skin_ratio < 0.10:
        return gray, 0.0

    return _crop_from_mask(gray, skin_mask, min_region, confidence_base=skin_ratio)


# ──────────────────────────────────────────────
# Strategy B: Contrast-Based Detection
# ──────────────────────────────────────────────

def _strategy_contrast(gray, min_region):
    """
    Detect fingerprint region via contrast/threshold segmentation.
    Best for: ink fingerprints on paper (dark print on light background).

    Uses Otsu thresholding to separate the dark fingerprint ink from
    the light paper, then finds the largest dark region.

    Returns:
        tuple: (cropped_image, confidence_score)
    """
    # Light blur to reduce noise
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # Otsu threshold — separates dark ink from light paper
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Check if we have a reasonable amount of dark pixels (fingerprint ink)
    dark_ratio = np.count_nonzero(binary) / binary.size
    if dark_ratio < 0.05 or dark_ratio > 0.60:
        # Too few (no print) or too many (image is mostly dark / not paper)
        return gray, 0.0

    # Morphological closing to connect nearby ink regions
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    # Confidence based on how "fingerprint-like" the dark ratio is
    # Peak confidence at ~15-25% dark pixels (typical for ink prints)
    if 0.10 <= dark_ratio <= 0.35:
        conf_base = 0.7
    else:
        conf_base = 0.3

    return _crop_from_mask(gray, closed, min_region, confidence_base=conf_base)


# ──────────────────────────────────────────────
# Strategy C: Edge Density Detection
# ──────────────────────────────────────────────

def _strategy_edge_density(gray, min_region):
    """
    Detect fingerprint region by finding the area with highest
    edge density. Fingerprint ridges produce dense parallel edges.

    Best for: generic fallback when color/contrast don't work.

    Returns:
        tuple: (cropped_image, confidence_score)
    """
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    edges = cv2.Canny(blurred, 30, 100)

    overall_edge_ratio = np.count_nonzero(edges) / edges.size
    if overall_edge_ratio < 0.01:
        return gray, 0.0

    # Dilate edges to create connected regions
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
    dilated = cv2.dilate(edges, kernel, iterations=2)

    # Close gaps
    closed = cv2.morphologyEx(dilated, cv2.MORPH_CLOSE, kernel)

    # Confidence is moderate — this is the fallback
    conf_base = min(0.5, overall_edge_ratio * 5)

    return _crop_from_mask(gray, closed, min_region, confidence_base=conf_base)


# ──────────────────────────────────────────────
# Shared Cropping Helper
# ──────────────────────────────────────────────

def _crop_from_mask(gray, mask, min_region, confidence_base=0.5):
    """
    Find the largest contour in a binary mask and crop the
    corresponding region from the grayscale image.

    Args:
        gray: Grayscale source image
        mask: Binary mask highlighting the region of interest
        min_region: Minimum acceptable contour area
        confidence_base: Base confidence score for this strategy

    Returns:
        tuple: (cropped_image, confidence_score)
    """
    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    if not contours:
        return gray, 0.0

    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)

    if area < min_region:
        return gray, 0.0

    # Crop with padding
    x, y, w, h = cv2.boundingRect(largest)
    padding = 20

    x1 = max(0, x - padding)
    y1 = max(0, y - padding)
    x2 = min(gray.shape[1], x + w + padding)
    y2 = min(gray.shape[0], y + h + padding)

    cropped = gray[y1:y2, x1:x2]

    # Scale confidence by how much of the image the region covers
    coverage = area / (gray.shape[0] * gray.shape[1])
    confidence = confidence_base * min(1.0, coverage * 3)

    logger.info(
        "Crop result: bbox=(%d,%d,%d,%d), area=%.0f, coverage=%.1f%%",
        x, y, w, h, area, coverage * 100
    )

    return cropped, confidence
