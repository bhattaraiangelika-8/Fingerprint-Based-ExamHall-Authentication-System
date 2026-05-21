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


def _get_padding_color(image, config):
    """Return padding fill value based on config ('white' or 'mean')."""
    color_setting = config.get('PADDING_COLOR', 'white')
    if color_setting == 'mean':
        return int(np.mean(image))
    return 255  # white


def resize_with_padding(image, target_size, padding_color=None):
    """
    Resize image to target_size while preserving aspect ratio.

    The image is scaled so its longer edge fits within target_size,
    then centered on a canvas of exactly target_size with padding.

    Args:
        image: numpy array (grayscale)
        target_size: tuple (width, height) for the output canvas
        padding_color: optional fill value; if None, uses config setting

    Returns:
        numpy array: Resized and padded image of shape (height, width)
    """
    config = getattr(settings, 'FINGERPRINT', {})
    if padding_color is None:
        padding_color = _get_padding_color(image, config)

    th, tw = target_size[1], target_size[0]  # target height, width
    h, w = image.shape[:2]

    # Compute scale so longer edge fits inside target
    scale = min(tw / w, th / h)
    new_w = int(w * scale)
    new_h = int(h * scale)

    # Resize while preserving aspect ratio
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    # Create canvas and compute centering offsets
    canvas = np.full((th, tw), padding_color, dtype=np.uint8)
    y_offset = (th - new_h) // 2
    x_offset = (tw - new_w) // 2

    canvas[y_offset:y_offset + new_h, x_offset:x_offset + new_w] = resized

    logger.info(
        "Resize with padding: original=%dx%d, scaled=%dx%d, canvas=%dx%d, "
        "padding=%s",
        w, h, new_w, new_h, tw, th,
        'mean' if config.get('PADDING_COLOR') == 'mean' else 'white',
    )

    return canvas

def normalize_image(image, target_size=None):
    """
    Normalize a fingerprint image.

    Operations:
        1. Convert to grayscale if needed
        2. Resize to standard resolution with aspect-ratio padding (default 400×500)
        3. Apply CLAHE for contrast normalization
        4. Normalize intensity to [0, 255]

    Args:
        image: numpy array (grayscale or BGR)
        target_size: tuple (width, height), defaults to settings.FINGERPRINT['NORMALIZED_SIZE']

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

    # ── Resize to target with aspect-ratio padding ──
    resized = resize_with_padding(gray, target_size)

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


def normalize_camera_image(image, target_size=None):
    """
    Aggressive normalization for camera-captured fingerprint photos.

    Camera photos typically have low contrast and uneven lighting.
    This function applies more aggressive enhancement to extract
    ridge/valley structure.

    Operations:
        1. Convert to grayscale if needed
        2. Resize to standard resolution with aspect-ratio padding (default 400×500)
        3. Apply aggressive CLAHE for contrast enhancement
        4. Apply adaptive thresholding to enhance ridges
        5. Normalize intensity to [0, 255]

    Args:
        image: numpy array (grayscale or BGR)
        target_size: tuple (width, height), defaults to settings.FINGERPRINT['NORMALIZED_SIZE']

    Returns:
        numpy array: Normalized grayscale image with enhanced ridges
    """
    if target_size is None:
        target_size = settings.FINGERPRINT['NORMALIZED_SIZE']

    # ── Convert to grayscale ──
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    # ── Resize to target with aspect-ratio padding ──
    resized = resize_with_padding(gray, target_size)

    # ── Aggressive CLAHE for low-contrast camera images ──
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(resized)

    # ── Gaussian blur to reduce noise before thresholding ──
    blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)

    # ── Adaptive threshold to enhance ridge/valley separation ──
    # This creates a binary-like image but preserves grayscale
    thresh = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11, 2
    )

    # ── Normalize intensity to full [0, 255] range ──
    normalized = cv2.normalize(
        thresh, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U
    )

    logger.info(
        "Camera image normalized (aggressive): size=%s, mean=%.1f, std=%.1f",
        target_size, np.mean(normalized), np.std(normalized)
    )

    return normalized
