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
from .normalizer import normalize_image
from .ridge_enhancer import enhance_ridges
from .noise_reducer import reduce_noise
from .orientation import normalize_orientation
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
    Full preprocessing pipeline for camera-captured fingerprint photos.

    Pipeline:
        1. Region detection & crop
        2. Normalization (resize + CLAHE)
        3. Ridge enhancement (Gabor)
        4. Noise reduction
        5. Orientation normalization
        6. Quality assessment

    Args:
        image_array: numpy array (BGR or grayscale)

    Returns:
        PreprocessingResult
    """
    steps = []

    # 1. Detect and crop fingerprint region
    logger.info("Step 1/6: Fingerprint region detection")
    cropped = detect_and_crop_fingerprint(image_array)
    steps.append('region_detection')

    # 2. Normalize image
    logger.info("Step 2/6: Image normalization")
    normalized = normalize_image(cropped)
    steps.append('normalization')

    # 3. Enhance ridges
    logger.info("Step 3/6: Ridge enhancement")
    enhanced = enhance_ridges(normalized)
    steps.append('ridge_enhancement')

    # 4. Reduce noise
    logger.info("Step 4/6: Noise reduction")
    cleaned = reduce_noise(enhanced)
    steps.append('noise_reduction')

    # 5. Normalize orientation
    logger.info("Step 5/6: Orientation normalization")
    oriented = normalize_orientation(cleaned)
    steps.append('orientation_normalization')

    # 6. Quality assessment
    logger.info("Step 6/6: Quality assessment")
    quality = assess_quality(oriented)
    steps.append('quality_assessment')

    return PreprocessingResult(oriented, quality, steps)


def preprocess_sensor_image(image_array):
    """
    Preprocessing pipeline for sensor-captured fingerprints.

    Sensor images require minimal preprocessing (no region detection,
    less normalization needed).

    Pipeline:
        1. Convert to grayscale
        2. Normalization (resize + CLAHE)
        3. Noise reduction (light)
        4. Quality assessment

    Args:
        image_array: numpy array (grayscale or BGR)

    Returns:
        PreprocessingResult
    """
    steps = []

    # 1. Convert to grayscale if needed
    if len(image_array.shape) == 3:
        image_array = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)

    # 2. Normalize
    logger.info("Sensor Step 1/3: Image normalization")
    normalized = normalize_image(image_array)
    steps.append('normalization')

    # 3. Light noise reduction
    logger.info("Sensor Step 2/3: Noise reduction")
    cleaned = reduce_noise(normalized)
    steps.append('noise_reduction')

    # 4. Quality assessment
    logger.info("Sensor Step 3/3: Quality assessment")
    quality = assess_quality(cleaned)
    steps.append('quality_assessment')

    return PreprocessingResult(cleaned, quality, steps)
