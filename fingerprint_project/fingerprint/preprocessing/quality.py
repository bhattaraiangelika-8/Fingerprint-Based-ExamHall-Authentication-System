"""
Quality Control Module
──────────────────────
Assesses fingerprint image quality and rejects images
that are too blurry, low-contrast, or noisy.
"""

import cv2
import numpy as np
import logging

logger = logging.getLogger('fingerprint')


class QualityResult:
    """Container for quality assessment results."""

    def __init__(self, blur_score, contrast_score, edge_density, overall_score):
        self.blur_score = blur_score
        self.contrast_score = contrast_score
        self.edge_density = edge_density
        self.overall_score = overall_score

    @property
    def is_acceptable(self):
        """Check if quality meets minimum threshold."""
        from django.conf import settings
        threshold = settings.FINGERPRINT.get('QUALITY_THRESHOLD', 40)
        return self.overall_score >= threshold

    def to_dict(self):
        return {
            'blur_score': round(self.blur_score, 2),
            'contrast_score': round(self.contrast_score, 2),
            'edge_density': round(self.edge_density, 2),
            'overall_score': round(self.overall_score, 2),
            'is_acceptable': self.is_acceptable,
        }


def assess_quality(image):
    """
    Assess fingerprint image quality.

    Metrics:
        - Blur detection (Laplacian variance)
        - Ridge contrast (local variance)
        - Edge density (Canny edge ratio)

    Args:
        image: numpy array (grayscale)

    Returns:
        QualityResult: Quality metrics and overall score
    """
    blur_score = _compute_blur_score(image)
    contrast_score = _compute_contrast_score(image)
    edge_density = _compute_edge_density(image)

    # Weighted overall score (0-100)
    overall = (
        blur_score * 0.35
        + contrast_score * 0.35
        + edge_density * 0.30
    )

    result = QualityResult(blur_score, contrast_score, edge_density, overall)

    logger.info(
        "Quality assessment: blur=%.1f, contrast=%.1f, edges=%.1f, overall=%.1f (%s)",
        blur_score, contrast_score, edge_density, overall,
        "PASS" if result.is_acceptable else "FAIL"
    )

    return result


def _compute_blur_score(image):
    """
    Detect blur using Laplacian variance.
    Higher variance = sharper image.
    Score normalized to 0-100.
    """
    laplacian = cv2.Laplacian(image, cv2.CV_64F)
    variance = laplacian.var()

    # Map variance to 0-100 score
    # < 50 → very blurry, > 500 → very sharp
    score = min(100, (variance / 500) * 100)
    return score


def _compute_contrast_score(image):
    """
    Measure ridge contrast via local standard deviation.
    Score normalized to 0-100.
    """
    # Compute local std deviation using a window
    kernel_size = 15
    mean = cv2.blur(image.astype(np.float64), (kernel_size, kernel_size))
    sqr_mean = cv2.blur(
        (image.astype(np.float64)) ** 2, (kernel_size, kernel_size)
    )
    local_std = np.sqrt(np.maximum(sqr_mean - mean ** 2, 0))

    avg_std = np.mean(local_std)

    # Map to 0-100 (good fingerprints have avg_std ~ 30-60)
    score = min(100, (avg_std / 60) * 100)
    return score


def _compute_edge_density(image):
    """
    Measure edge density using Canny edges.
    Good fingerprints have moderate edge density.
    Score normalized to 0-100.
    """
    edges = cv2.Canny(image, 50, 150)
    edge_ratio = np.count_nonzero(edges) / edges.size

    # Ideal edge ratio for fingerprints: ~0.05-0.15
    # Map to 0-100, peak at 0.10
    if edge_ratio < 0.01:
        score = edge_ratio / 0.01 * 30  # Very few edges
    elif edge_ratio < 0.05:
        score = 30 + (edge_ratio - 0.01) / 0.04 * 40
    elif edge_ratio < 0.15:
        score = 70 + (edge_ratio - 0.05) / 0.10 * 30
    else:
        score = max(50, 100 - (edge_ratio - 0.15) / 0.10 * 30)

    return min(100, score)
