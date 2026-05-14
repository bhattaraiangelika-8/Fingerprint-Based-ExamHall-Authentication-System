"""
Preprocessing Pipeline Orchestrator
────────────────────────────────────
Chains all preprocessing steps into a single pipeline with separate
entry points for camera and sensor images.

The pipeline runs the proven minutiae extraction pipeline:
  normalize → segment/ROI → orientation → frequency → gabor filter
  → skeletonize → crossing number minutiae → poincaré singularities

Sensor-specific steps preserved from the original:
  - Black bar cropping: The AS608 outputs a black artifact row at the
    top that severely distorts processing. We strip it first.
  - Border masking: Noisy side pixels are neutralized.

Camera-specific steps preserved:
  - Region detection & crop: Isolates fingerprint from photo
"""

import cv2
import numpy as np
import logging

from .region_detector import detect_and_crop_fingerprint
from .quality import assess_quality
from .minutiae_core import run_minutiae_pipeline

logger = logging.getLogger('fingerprint')


# ──────────────────────────────────────────────
# Sensor Artifact Helpers
# ──────────────────────────────────────────────

def _crop_sensor_black_top(image):
    """
    Remove the black bar artifact at the top of AS608 sensor images.

    The AS608/R503 sensors produce a strip of near-zero pixels at the
    top of their raw output (typically 5-25 rows). When processing
    this, the local contrast calculation is skewed for the entire image,
    degrading ridge visibility and feature quality significantly.

    Strategy: scan rows from the top; any row whose mean pixel value is
    below 40 is considered part of the artifact band. We stop scanning
    as soon as we hit a 'real' row so we don't accidentally eat into
    the fingerprint itself.
    """
    h = image.shape[0]
    top_crop = 0

    for r in range(min(40, h)):
        if np.mean(image[r, :]) < 40:
            top_crop = r + 1
        else:
            break  # First non-black row — stop here

    if top_crop > 0:
        logger.info("Sensor: Cropped %d black artifact rows from top", top_crop)
        return image[top_crop:, :]
    return image


def _mask_sensor_borders(image, border_px=8):
    """
    Neutralize noisy border columns on sensor images.

    The AS608 side borders often contain bright/dark edge artefacts
    that generate spurious keypoints. Replace them with the image mean
    so they blend into the background.
    """
    result = image.copy()
    fill = int(np.mean(image))
    result[:, :border_px] = fill
    result[:, -border_px:] = fill
    return result


class PreprocessingResult:
    """Container for preprocessing output."""

    def __init__(self, processed_image, quality_result, steps_completed,
                 minutiae_data=None):
        self.processed_image = processed_image
        self.quality_result = quality_result
        self.steps_completed = steps_completed
        self.minutiae_data = minutiae_data  # Full pipeline output dict

    def to_dict(self):
        result = {
            'quality': self.quality_result.to_dict(),
            'steps_completed': self.steps_completed,
            'image_shape': list(self.processed_image.shape),
        }
        if self.minutiae_data:
            result['minutiae_count'] = len(
                self.minutiae_data.get('minutiae_points', [])
            )
            result['singularities_count'] = len(
                self.minutiae_data.get('singularities_points', [])
            )
        return result


def preprocess_camera_image(image_array):
    """
    Preprocessing pipeline for camera-captured fingerprint photos.

    Pipeline:
        1. Region detection & crop
        2. Convert to grayscale + resize to 512×512
        3. Run full minutiae extraction pipeline
           (normalize → segment → orientation → frequency
            → gabor → skeletonize → crossing number → poincaré)
        4. Quality assessment

    Args:
        image_array: numpy array (BGR or grayscale)

    Returns:
        PreprocessingResult with minutiae data
    """
    steps = []

    # 1. Detect and crop fingerprint region
    logger.info("Camera Step 1: Fingerprint region detection")
    cropped = detect_and_crop_fingerprint(image_array)
    steps.append('region_detection')

    # 2. Convert to grayscale and resize
    logger.info("Camera Step 2: Grayscale + resize to 512x512")
    if len(cropped.shape) == 3:
        gray = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY)
    else:
        gray = cropped.copy()
    resized = cv2.resize(gray, (512, 512), interpolation=cv2.INTER_CUBIC)
    steps.append('resize_512')

    # 3. Run full minutiae extraction pipeline
    logger.info("Camera Step 3: Running minutiae extraction pipeline...")
    minutiae_data = run_minutiae_pipeline(resized, block_size=16)
    steps.append('normalization')
    steps.append('segmentation')
    steps.append('orientation')
    steps.append('frequency')
    steps.append('gabor_filter')
    steps.append('skeletonize')
    steps.append('minutiae_detection')
    steps.append('singularity_detection')

    # 4. Quality assessment (on the gabor-enhanced image)
    logger.info("Camera Step 4: Quality assessment")
    quality = assess_quality(minutiae_data['gabor_img'])
    steps.append('quality_assessment')

    # The processed image stored for matching is the skeletonized thin image
    return PreprocessingResult(
        processed_image=resized,
        quality_result=quality,
        steps_completed=steps,
        minutiae_data=minutiae_data,
    )


def preprocess_sensor_image(image_array):
    """
    Preprocessing pipeline for sensor-captured fingerprints.

    Pipeline:
        1. Convert to grayscale
        2. Crop black bar artifact (AS608 top-row artifact)
        3. Mask noisy border columns
        4. Resize to 512×512
        5. Run full minutiae extraction pipeline
        6. Quality assessment

    Args:
        image_array: numpy array (grayscale or BGR)

    Returns:
        PreprocessingResult with minutiae data
    """
    steps = []

    # 1. Convert to grayscale if needed
    if len(image_array.shape) == 3:
        image_array = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)

    # 2. Crop black bar artifact at top (AS608 specific)
    logger.info("Sensor Step 1: Black bar artifact removal")
    image_array = _crop_sensor_black_top(image_array)
    steps.append('black_bar_crop')

    # 3. Mask noisy side borders
    logger.info("Sensor Step 2: Border noise masking")
    image_array = _mask_sensor_borders(image_array, border_px=8)
    steps.append('border_mask')

    # 4. Resize to standard resolution
    logger.info("Sensor Step 3: Resize to 512x512")
    resized = cv2.resize(image_array, (512, 512), interpolation=cv2.INTER_CUBIC)
    steps.append('resize_512')

    # 5. Run full minutiae extraction pipeline
    logger.info("Sensor Step 4: Running minutiae extraction pipeline...")
    minutiae_data = run_minutiae_pipeline(resized, block_size=16)
    steps.append('normalization')
    steps.append('segmentation')
    steps.append('orientation')
    steps.append('frequency')
    steps.append('gabor_filter')
    steps.append('skeletonize')
    steps.append('minutiae_detection')
    steps.append('singularity_detection')

    # 6. Quality assessment
    logger.info("Sensor Step 5: Quality assessment")
    quality = assess_quality(minutiae_data['gabor_img'])
    steps.append('quality_assessment')

    return PreprocessingResult(
        processed_image=resized,
        quality_result=quality,
        steps_completed=steps,
        minutiae_data=minutiae_data,
    )
