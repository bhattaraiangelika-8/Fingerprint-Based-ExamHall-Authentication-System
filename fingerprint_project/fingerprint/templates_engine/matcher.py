"""
Template Matching Module
────────────────────────
Matches fingerprint templates using SIFT, ORB, BFMatcher,
and FLANN. Also supports the fingerprints-matching library
for minutiae-based scoring.
"""

import cv2
import numpy as np
import logging

logger = logging.getLogger('fingerprint')


class MatchResult:
    """Container for match results."""

    def __init__(self, score, method, matched_template_id=None):
        self.score = score
        self.method = method
        self.matched_template_id = matched_template_id

    @property
    def is_match(self):
        from django.conf import settings
        threshold = settings.FINGERPRINT.get('MATCH_THRESHOLD', 30)
        return self.score >= threshold

    @property
    def interpretation(self):
        if self.score < 20:
            return 'NO_MATCH'
        elif self.score < 30:
            return 'WEAK_SIMILARITY'
        elif self.score < 40:
            return 'POSSIBLE_MATCH'
        else:
            return 'STRONG_MATCH'

    def to_dict(self):
        return {
            'score': round(self.score, 2),
            'method': self.method,
            'is_match': self.is_match,
            'interpretation': self.interpretation,
            'matched_template_id': self.matched_template_id,
        }


def match_fingerprints(image1, image2, method='combined'):
    """
    Match two fingerprint images using feature-based methods.

    Args:
        image1: numpy array (grayscale, preprocessed)
        image2: numpy array (grayscale, preprocessed)
        method: 'sift', 'orb', 'flann', or 'combined'

    Returns:
        MatchResult
    """
    scores = {}

    if method in ('sift', 'combined'):
        scores['sift'] = _match_sift(image1, image2)

    if method in ('orb', 'combined'):
        scores['orb'] = _match_orb(image1, image2)

    if method in ('flann', 'combined'):
        scores['flann'] = _match_flann(image1, image2)

    if not scores:
        return MatchResult(0.0, method)

    # Combined: weighted average
    if method == 'combined' and len(scores) > 1:
        weights = {'sift': 0.4, 'orb': 0.3, 'flann': 0.3}
        total_weight = sum(weights.get(k, 0.33) for k in scores)
        weighted_score = sum(
            scores[k] * weights.get(k, 0.33) for k in scores
        ) / total_weight
        best_method = max(scores, key=scores.get)
        final_score = weighted_score
    else:
        best_method = max(scores, key=scores.get)
        final_score = scores[best_method]

    logger.info(
        "Match result: method=%s, score=%.2f, scores=%s",
        method, final_score,
        {k: f"{v:.2f}" for k, v in scores.items()}
    )

    return MatchResult(final_score, method)


def match_multi_template(probe_image, stored_images, stored_ids=None):
    """
    Match a probe fingerprint against multiple enrolled templates.

    Args:
        probe_image: numpy array (grayscale)
        stored_images: list of numpy arrays (stored fingerprint images)
        stored_ids: list of template IDs (optional)

    Returns:
        MatchResult: Best match result
    """
    best_result = MatchResult(0.0, 'combined')

    for i, stored_img in enumerate(stored_images):
        result = match_fingerprints(probe_image, stored_img, method='combined')

        template_id = stored_ids[i] if stored_ids and i < len(stored_ids) else i

        if result.score > best_result.score:
            best_result = MatchResult(result.score, result.method, template_id)

    logger.info(
        "Multi-template match: best_score=%.2f, template_id=%s, %d templates checked",
        best_result.score,
        best_result.matched_template_id,
        len(stored_images),
    )

    return best_result


# ────────────────────────────────────────────────────
# Feature Matching Implementations
# ────────────────────────────────────────────────────


def _match_sift(img1, img2):
    """
    Match using SIFT features + BFMatcher.
    Returns normalized score (0-100).
    """
    sift = cv2.SIFT_create()

    kp1, des1 = sift.detectAndCompute(img1, None)
    kp2, des2 = sift.detectAndCompute(img2, None)

    if des1 is None or des2 is None or len(kp1) < 2 or len(kp2) < 2:
        return 0.0

    bf = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
    matches = bf.knnMatch(des1, des2, k=2)

    # Lowe's ratio test
    good_matches = []
    for match_pair in matches:
        if len(match_pair) == 2:
            m, n = match_pair
            if m.distance < 0.75 * n.distance:
                good_matches.append(m)

    # Normalize score
    max_possible = min(len(kp1), len(kp2))
    if max_possible == 0:
        return 0.0

    score = (len(good_matches) / max_possible) * 100
    return min(100, score)


def _match_orb(img1, img2):
    """
    Match using ORB features + BFMatcher with Hamming distance.
    Returns normalized score (0-100).
    """
    orb = cv2.ORB_create(nfeatures=1000)

    kp1, des1 = orb.detectAndCompute(img1, None)
    kp2, des2 = orb.detectAndCompute(img2, None)

    if des1 is None or des2 is None or len(kp1) < 2 or len(kp2) < 2:
        return 0.0

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    matches = bf.knnMatch(des1, des2, k=2)

    # Lowe's ratio test
    good_matches = []
    for match_pair in matches:
        if len(match_pair) == 2:
            m, n = match_pair
            if m.distance < 0.75 * n.distance:
                good_matches.append(m)

    max_possible = min(len(kp1), len(kp2))
    if max_possible == 0:
        return 0.0

    score = (len(good_matches) / max_possible) * 100
    return min(100, score)


def _match_flann(img1, img2):
    """
    Match using SIFT features + FLANN-based matcher.
    FLANN is faster than brute-force for large feature sets.
    Returns normalized score (0-100).
    """
    sift = cv2.SIFT_create()

    kp1, des1 = sift.detectAndCompute(img1, None)
    kp2, des2 = sift.detectAndCompute(img2, None)

    if des1 is None or des2 is None or len(kp1) < 2 or len(kp2) < 2:
        return 0.0

    # FLANN parameters for SIFT
    FLANN_INDEX_KDTREE = 1
    index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
    search_params = dict(checks=50)

    flann = cv2.FlannBasedMatcher(index_params, search_params)
    matches = flann.knnMatch(des1, des2, k=2)

    # Lowe's ratio test
    good_matches = []
    for match_pair in matches:
        if len(match_pair) == 2:
            m, n = match_pair
            if m.distance < 0.75 * n.distance:
                good_matches.append(m)

    max_possible = min(len(kp1), len(kp2))
    if max_possible == 0:
        return 0.0

    score = (len(good_matches) / max_possible) * 100
    return min(100, score)
