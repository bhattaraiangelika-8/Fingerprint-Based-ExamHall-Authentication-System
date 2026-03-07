"""
Image Validation Module
───────────────────────
Validates uploaded fingerprint images for format, size, resolution,
and finger presence before processing.
"""

import io
import logging
import numpy as np
from PIL import Image
from django.conf import settings

logger = logging.getLogger('fingerprint')

# Fingerprint config from settings
FP_CONFIG = settings.FINGERPRINT


class ValidationError(Exception):
    """Raised when image validation fails."""
    pass


def validate_image(image_file):
    """
    Validate an uploaded fingerprint image.

    Args:
        image_file: Django UploadedFile or file-like object

    Returns:
        PIL.Image: Validated image object

    Raises:
        ValidationError: If any validation check fails
    """
    # ── Check file size ──
    image_file.seek(0, 2)  # Seek to end
    file_size = image_file.tell()
    image_file.seek(0)

    max_bytes = FP_CONFIG['MAX_FILE_SIZE_MB'] * 1024 * 1024
    if file_size > max_bytes:
        raise ValidationError(
            f"File size {file_size / (1024*1024):.1f}MB exceeds "
            f"maximum {FP_CONFIG['MAX_FILE_SIZE_MB']}MB"
        )

    if file_size == 0:
        raise ValidationError("Empty file uploaded")

    # ── Check format ──
    try:
        img = Image.open(image_file)
        img.verify()
        image_file.seek(0)
        img = Image.open(image_file)  # Re-open after verify
    except Exception:
        raise ValidationError(
            "Invalid image file. Accepted formats: JPEG, PNG"
        )

    if img.format not in FP_CONFIG['ACCEPTED_FORMATS']:
        raise ValidationError(
            f"Unsupported format '{img.format}'. "
            f"Accepted: {', '.join(FP_CONFIG['ACCEPTED_FORMATS'])}"
        )

    # ── Check resolution ──
    width, height = img.size
    min_w = FP_CONFIG['MIN_IMAGE_WIDTH']
    min_h = FP_CONFIG['MIN_IMAGE_HEIGHT']

    if width < min_w or height < min_h:
        raise ValidationError(
            f"Image resolution {width}×{height} is below minimum "
            f"{min_w}×{min_h} pixels"
        )

    # ── Check for finger presence (basic skin detection) ──
    if not _detect_finger_presence(img):
        raise ValidationError(
            "No fingerprint region detected in the image. "
            "Please capture a clear fingerprint photo."
        )

    logger.info(
        "Image validated: format=%s, size=%dx%d, file_size=%.1fKB",
        img.format, width, height, file_size / 1024
    )

    return img


def _detect_finger_presence(img):
    """
    Basic finger presence detection using skin color segmentation.

    Uses HSV color space to detect skin-like regions. If sufficient
    skin pixels exist, a finger is likely present.
    """
    import cv2

    # Convert PIL to OpenCV format
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img_array = np.array(img)
    hsv = cv2.cvtColor(img_array, cv2.COLOR_RGB2HSV)

    # Skin color range in HSV
    lower_skin = np.array([0, 20, 70], dtype=np.uint8)
    upper_skin = np.array([20, 255, 255], dtype=np.uint8)
    mask1 = cv2.inRange(hsv, lower_skin, upper_skin)

    # Second skin range for darker tones
    lower_skin2 = np.array([170, 20, 70], dtype=np.uint8)
    upper_skin2 = np.array([180, 255, 255], dtype=np.uint8)
    mask2 = cv2.inRange(hsv, lower_skin2, upper_skin2)

    skin_mask = mask1 | mask2
    skin_ratio = np.count_nonzero(skin_mask) / skin_mask.size

    # If at least 10% of pixels are skin-colored, finger is present
    return skin_ratio > 0.10
