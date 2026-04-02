"""
Preprocessing Pipeline Orchestrator
────────────────────────────────────
Chains all preprocessing steps into a single pipeline
with separate entry points for camera and sensor images.
"""

import cv2
import numpy as np
import logging

from .region_detector import detect_and_crop_fingerprint
from .noise_reducer import reduce_noise
from .quality import assess_quality

logger = logging.getLogger('fingerprint')


class PreprocessingResult:
    """Container for preprocessing output."""

    def __init__(self, processed_image, quality_result, steps_completed):
        self.processed_image = processed_image
        self.quality_result = quality_result
        self.steps_completed = steps_completed

    def to_dict(self):
        return {
            'quality': self.quality_result.to_dict(),
            'steps_completed': self.steps_completed,
            'image_shape': list(self.processed_image.shape),
        }


def preprocess_camera_image(image_array):
    """
    Preprocessing pipeline for camera-captured fingerprint photos.

    Uses aggressive normalization to enhance low-contrast camera images
    so they match sensor-captured fingerprints for comparison.

    Pipeline:
        1. Region detection & crop
        2. Resize to 512x512
        3. CLAHE contrast enhancement
        4. Ridge enhancement (Gabor filters)
        5. Binarization (adaptive threshold)
        6. Noise reduction
        7. Quality assessment

    Args:
        image_array: numpy array (BGR or grayscale)

    Returns:
        PreprocessingResult
    """
    steps = []

    # 1. Detect and crop fingerprint region
    logger.info("Step 1/7: Fingerprint region detection")
    cropped = detect_and_crop_fingerprint(image_array)
    steps.append('region_detection')

    # 2. Convert to grayscale and resize
    logger.info("Step 2/7: Image normalization")
    if len(cropped.shape) == 3:
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    else:
        gray = cropped.copy()
    target_size = (512, 512)
    resized = cv2.resize(gray, target_size, interpolation=cv2.INTER_CUBIC)
    steps.append('normalization')

    # 3. CLAHE contrast enhancement (aggressive for camera)
    logger.info("Step 3/7: CLAHE contrast enhancement")
    clahe = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(resized)
    steps.append('clahe')

    # 4. Ridge enhancement using Gabor filters
    logger.info("Step 4/7: Ridge enhancement")
    enhanced = _apply_gabor_enhancement(enhanced)
    steps.append('ridge_enhancement')

    # 5. Binarization for clean black-and-white output
    logger.info("Step 5/7: Binarization")
    blurred = cv2.GaussianBlur(enhanced, (5, 5), 0)
    binary = cv2.adaptiveThreshold(
        blurred, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11, 2
    )
    steps.append('binarization')

    # 6. Noise reduction
    logger.info("Step 6/7: Noise reduction")
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel)
    steps.append('noise_reduction')

    # 7. Quality assessment
    logger.info("Step 7/7: Quality assessment")
    quality = assess_quality(cleaned)
    steps.append('quality_assessment')

    return PreprocessingResult(cleaned, quality, steps)


def preprocess_sensor_image(image_array):
    """
    Preprocessing pipeline for sensor-captured fingerprints.

    Enhances ridges and binarizes for clean black-and-white output.

    Pipeline:
        1. Convert to grayscale
        2. Resize to 512x512
        3. CLAHE contrast enhancement
        4. Ridge enhancement (Gabor filters)
        5. Binarization (adaptive threshold)
        6. Noise reduction (light)
        7. Quality assessment

    Args:
        image_array: numpy array (grayscale or BGR)

    Returns:
        PreprocessingResult
    """
    steps = []

    # 1. Convert to grayscale if needed
    if len(image_array.shape) == 3:
        image_array = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)

    # 2. Resize to standard resolution
    logger.info("Sensor Step 1/6: Image normalization")
    target_size = (512, 512)
    resized = cv2.resize(image_array, target_size, interpolation=cv2.INTER_CUBIC)
    steps.append('resize')

    # 3. CLAHE contrast enhancement
    logger.info("Sensor Step 2/6: CLAHE contrast enhancement")
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(resized)
    steps.append('clahe')

    # 4. Ridge enhancement using Gabor filters
    logger.info("Sensor Step 3/6: Ridge enhancement")
    enhanced = _apply_gabor_enhancement(enhanced)
    steps.append('ridge_enhancement')

    # 5. Binarization for clean black-and-white output
    logger.info("Sensor Step 4/6: Binarization")
    binary = cv2.adaptiveThreshold(
        enhanced, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11, 2
    )
    steps.append('binarization')

    # 6. Light noise reduction
    logger.info("Sensor Step 5/6: Noise reduction")
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel)
    steps.append('noise_reduction')

    # 7. Quality assessment
    logger.info("Sensor Step 6/6: Quality assessment")
    quality = assess_quality(cleaned)
    steps.append('quality_assessment')

    return PreprocessingResult(cleaned, quality, steps)


def _apply_gabor_enhancement(image):
    """
    Enhance fingerprint ridges using Gabor filter bank.
    Applies filters at multiple orientations to enhance ridge structure.
    """
    # Gabor filter parameters
    ksize = 21
    sigma = 4.0
    lambd = 10.0
    gamma = 0.5

    # Apply Gabor filters at 8 orientations
    enhanced = np.zeros_like(image, dtype=np.float64)
    for theta in np.arange(0, np.pi, np.pi / 8):
        kernel = cv2.getGaborKernel(
            (ksize, ksize), sigma, theta, lambd, gamma, 0, ktype=cv2.CV_64F
        )
        filtered = cv2.filter2D(image.astype(np.float64), cv2.CV_64F, kernel)
        enhanced = np.maximum(enhanced, filtered)

    # Normalize back to uint8
    enhanced = cv2.normalize(enhanced, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
    return enhanced
