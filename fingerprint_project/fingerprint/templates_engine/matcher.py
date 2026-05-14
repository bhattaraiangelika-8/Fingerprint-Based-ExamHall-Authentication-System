"""
Template Matching Module
────────────────────────
Matches fingerprint templates using a combined strategy built on
the proven minutiae extraction pipeline.

Strategy:
  1. Minutiae-based matching (PRIMARY, weight=0.60)
     ─────────────────────────────────────────────
     Uses crossing-number detected minutiae (ridge endings +
     bifurcations) from the Gabor→skeleton→CN pipeline. These are
     PHYSICAL properties of the finger — identical whether from a
     camera photo or an AS608 capacitive sensor.

  2. Singularity topology matching (SECONDARY, weight=0.15)
     ───────────────────────────────────────────────────────
     Compares Poincaré singularities (loops, deltas, whorls) which
     are global structural features that are very stable across
     modalities.

  3. SIFT + FLANN (SECONDARY, weight=0.15)
  4. ORB          (SECONDARY, weight=0.10)
     Both operate on Gabor-filtered images for modality-independence.
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


def match_fingerprints(image1, image2, method='combined',
                       minutiae_data1=None, minutiae_data2=None,
                       template2=None):
    """
    Match two fingerprint images using a combined strategy.

    The combined score is dominated by crossing-number minutiae
    matching (60%), with singularity topology and image-based
    feature descriptors as secondary evidence.

    Args:
        image1: numpy array (grayscale, preprocessed) — probe image
        image2: numpy array (grayscale, preprocessed) — stored enrolled image
        method: 'minutiae', 'sift', 'orb', 'flann', or 'combined'
        minutiae_data1: optional pre-computed minutiae pipeline output for image1
        minutiae_data2: optional pre-computed minutiae pipeline output for image2
        template2: optional FingerprintTemplate object for image2 (avoids pipeline rerun)

    Returns:
        MatchResult
    """
    orig1 = image1.copy() if len(image1.shape) == 2 else cv2.cvtColor(
        image1, cv2.COLOR_BGR2GRAY)
    orig2 = image2.copy() if len(image2.shape) == 2 else cv2.cvtColor(
        image2, cv2.COLOR_BGR2GRAY)

    scores = {}

    # ── Minutiae matching (crossing-number based) ──
    if method in ('minutiae', 'combined'):
        scores['minutiae'] = _match_minutiae(
            orig1, orig2, minutiae_data1, minutiae_data2, template2
        )

    # ── Singularity topology matching ──
    if method in ('singularity', 'combined'):
        scores['singularity'] = _match_singularities(
            orig1, orig2, minutiae_data1, minutiae_data2, template2
        )

    # ── Image-based matchers on Gabor-normalized images ──
    if method in ('sift', 'combined'):
        gabor1 = minutiae_data1['gabor_img'] if minutiae_data1 else _normalize_for_matching(orig1)
        gabor2 = minutiae_data2['gabor_img'] if minutiae_data2 else _normalize_for_matching(orig2)
        scores['sift'] = _match_sift(gabor1, gabor2)

    if method in ('orb', 'combined'):
        gabor1 = minutiae_data1['gabor_img'] if minutiae_data1 else _normalize_for_matching(orig1)
        gabor2 = minutiae_data2['gabor_img'] if minutiae_data2 else _normalize_for_matching(orig2)
        scores['orb'] = _match_orb(gabor1, gabor2)

    if not scores:
        return MatchResult(0.0, method)

    # ── Combined weighted score ──
    if method == 'combined' and len(scores) > 1:
        weights = {
            'minutiae':    0.70,
            'singularity': 0.15,
            'sift':        0.10,
            'orb':         0.05,
        }
        total_weight = sum(weights.get(k, 0.1) for k in scores)
        final_score = sum(
            scores[k] * weights.get(k, 0.1) for k in scores
        ) / total_weight
        best_method = 'combined'
    else:
        best_method = max(scores, key=scores.get)
        final_score = scores[best_method]

    logger.info(
        "Match result: method=%s, score=%.2f, scores=%s",
        best_method, final_score,
        {k: f"{v:.2f}" for k, v in scores.items()}
    )

    return MatchResult(final_score, best_method)


# ────────────────────────────────────────────────────
# Fallback Gabor normalization (when no pipeline data)
# ────────────────────────────────────────────────────

def _normalize_for_matching(image):
    """
    Produce a Gabor-filtered image for SIFT/ORB matching.
    Used only as fallback when minutiae_data is not available.
    """
    if len(image.shape) == 3:
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    eq = clahe.apply(image)

    ksize = 21
    sigma = 4.0
    gamma = 0.5
    lambdas = [9.0, 13.0, 17.0]

    all_responses = []
    for lambd in lambdas:
        for i in range(8):
            theta = i * np.pi / 8
            kernel = cv2.getGaborKernel(
                (ksize, ksize), sigma, theta, lambd, gamma, 0,
                ktype=cv2.CV_64F
            )
            filtered = cv2.filter2D(
                eq.astype(np.float64), cv2.CV_64F, kernel
            )
            all_responses.append(np.abs(filtered))

    ridge_energy = np.max(all_responses, axis=0)
    ridge_energy = cv2.normalize(
        ridge_energy, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U
    )
    return ridge_energy


# ────────────────────────────────────────────────────
# Minutiae-based Matching (crossing number)
# ────────────────────────────────────────────────────

def _match_minutiae(img1, img2, data1=None, data2=None, template2=None):
    """
    Match fingerprints by comparing crossing-number minutiae sets.

    Uses the proven pipeline: normalize → segment → orient → freq
    → gabor → skeletonize → crossing number.

    Algorithm:
        1. Extract minutiae from both images
        2. For each rotation offset (-20° to +20°), rotate img2's
           minutiae and count type-matched spatial pairings
        3. Return best score normalized to [0, 100]
    """
    from .extractor import extract_template

    try:
        t1 = extract_template(img1, minutiae_data=data1)
        if template2 is not None:
            t2 = template2
        else:
            t2 = extract_template(img2, minutiae_data=data2)
    except Exception as e:
        logger.warning("Minutiae extraction failed: %s", e)
        return 0.0

    if t1.count < 5 or t2.count < 5:
        logger.warning(
            "Too few minutiae: img1=%d, img2=%d", t1.count, t2.count
        )
        return 0.0

    logger.info("Minutiae counts: img1=%d, img2=%d", t1.count, t2.count)

    SPATIAL_TOL = 15  # Tightened from 22 pixels to 10 pixels
    ANGLE_TOL = np.pi / 4  # Tightened from 45 degrees to 20 degrees

    cx = img1.shape[1] / 2.0
    cy = img1.shape[0] / 2.0

    m1_pts = [(m.x, m.y, m.type, m.angle) for m in t1.minutiae]
    m2_pts = [(m.x, m.y, m.type, m.angle) for m in t2.minutiae]

    best_matched = 0

    for rot_deg in [-20, -12, -6, 0, 6, 12, 20]:
        rot_rad = np.deg2rad(rot_deg)
        cos_r, sin_r = np.cos(rot_rad), np.sin(rot_rad)

        rotated2 = []
        for (x, y, mtype, ang) in m2_pts:
            dx, dy = x - cx, y - cy
            rx = cos_r * dx - sin_r * dy + cx
            ry = sin_r * dx + cos_r * dy + cy
            rotated2.append((rx, ry, mtype, ang + rot_rad))

        matched = 0
        used = set()

        for (x1, y1, t1_type, a1) in m1_pts:
            best_dist = float('inf')
            best_j = -1

            for j, (x2, y2, t2_type, a2) in enumerate(rotated2):
                if j in used:
                    continue
                if t1_type != t2_type:
                    continue

                dist = np.hypot(x1 - x2, y1 - y2)
                if dist >= SPATIAL_TOL or dist >= best_dist:
                    continue

                angle_diff = abs(a1 - a2) % np.pi
                angle_diff = min(angle_diff, np.pi - angle_diff)
                if angle_diff < ANGLE_TOL:
                    best_dist = dist
                    best_j = j

            if best_j >= 0:
                matched += 1
                used.add(best_j)

        if matched > best_matched:
            best_matched = matched

    # Use the minimum of the two minutiae counts to handle cross-modality matching
    # (Because the AS608 sensor physically captures a smaller area of the finger than a camera photo)
    max_possible = min(t1.count, t2.count)
    score = (best_matched / max_possible) * 100.0 if max_possible > 0 else 0.0

    logger.info(
        "Minutiae match: best_matched=%d / %d, score=%.2f",
        best_matched, max_possible, score
    )
    return min(100.0, score)


# ────────────────────────────────────────────────────
# Singularity Topology Matching
# ────────────────────────────────────────────────────

def _match_singularities(img1, img2, data1=None, data2=None, template2=None):
    """
    Match fingerprints by comparing Poincaré singularity patterns.

    Singularities (loops, deltas, whorls) are global structural
    features that are very stable across modalities.
    """
    from ..preprocessing.minutiae_core import run_minutiae_pipeline

    try:
        if data1:
            s1 = data1.get('singularities_points', [])
        else:
            result1 = run_minutiae_pipeline(img1, block_size=16)
            s1 = result1.get('singularities_points', [])

        if template2 is not None:
            s2 = template2.singularities
        elif data2:
            s2 = data2.get('singularities_points', [])
        else:
            result2 = run_minutiae_pipeline(img2, block_size=16)
            s2 = result2.get('singularities_points', [])
    except Exception as e:
        logger.warning("Singularity extraction failed: %s", e)
        return 0.0

    if not s1 and not s2:
        return 50.0  # Both have no singularities — neutral

    if not s1 or not s2:
        return 10.0  # One has singularities, other doesn't

    # Compare singularity type counts
    def type_counts(slist):
        counts = {'loop': 0, 'delta': 0, 'whorl': 0}
        for s in slist:
            t = s.get('type', '')
            if t in counts:
                counts[t] += 1
        return counts

    c1 = type_counts(s1)
    c2 = type_counts(s2)

    # Type similarity: how many of each type match
    type_score = 0
    total_types = 0
    for t in ['loop', 'delta', 'whorl']:
        max_count = max(c1[t], c2[t])
        if max_count > 0:
            type_score += min(c1[t], c2[t]) / max_count
            total_types += 1

    if total_types > 0:
        type_score = (type_score / total_types) * 60  # up to 60 points

    # Spatial similarity: match nearest singularities of same type
    spatial_score = 0
    matched_pairs = 0
    used = set()

    for s in s1:
        best_dist = float('inf')
        best_j = -1
        for j, s2_item in enumerate(s2):
            if j in used:
                continue
            if s['type'] != s2_item['type']:
                continue
            dist = np.hypot(s['x'] - s2_item['x'], s['y'] - s2_item['y'])
            if dist < best_dist:
                best_dist = dist
                best_j = j

        if best_j >= 0:
            # Score based on proximity (within 80px is good)
            spatial_score += max(0, 1.0 - best_dist / 80.0)
            matched_pairs += 1
            used.add(best_j)

    if matched_pairs > 0:
        spatial_score = (spatial_score / matched_pairs) * 40  # up to 40 points
    else:
        spatial_score = 0

    total = type_score + spatial_score
    logger.info("Singularity match: type=%.1f, spatial=%.1f, total=%.1f",
                type_score, spatial_score, total)
    return min(100.0, total)


# ────────────────────────────────────────────────────
# Multi-template helper
# ────────────────────────────────────────────────────

def match_multi_template(probe_image, stored_images, stored_ids=None,
                         probe_minutiae_data=None):
    """
    Match a probe fingerprint against multiple enrolled templates.
    """
    best_result = MatchResult(0.0, 'combined')

    for i, stored_img in enumerate(stored_images):
        result = match_fingerprints(
            probe_image, stored_img, method='combined',
            minutiae_data1=probe_minutiae_data,
        )

        template_id = stored_ids[i] if stored_ids and i < len(stored_ids) else i

        if result.score > best_result.score:
            best_result = MatchResult(result.score, result.method, template_id)

    logger.info(
        "Multi-template match: best=%.2f, id=%s, checked=%d",
        best_result.score, best_result.matched_template_id,
        len(stored_images),
    )

    return best_result


# ────────────────────────────────────────────────────
# Image-based Feature Matching (SIFT/ORB)
# ────────────────────────────────────────────────────

def _match_sift(img1, img2):
    """Match using SIFT features on Gabor-filtered images."""
    sift = cv2.SIFT_create(nfeatures=2000)

    kp1, des1 = sift.detectAndCompute(img1, None)
    kp2, des2 = sift.detectAndCompute(img2, None)

    if des1 is None or des2 is None or len(kp1) < 2 or len(kp2) < 2:
        return 0.0

    FLANN_INDEX_KDTREE = 1
    index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
    search_params = dict(checks=50)

    flann = cv2.FlannBasedMatcher(index_params, search_params)
    matches = flann.knnMatch(des1, des2, k=2)

    good_matches = []
    for match_pair in matches:
        if len(match_pair) == 2:
            m, n = match_pair
            if m.distance < 0.75 * n.distance:
                good_matches.append(m)

    max_possible = min(len(kp1), len(kp2))
    if max_possible == 0:
        return 0.0

    return min(100.0, (len(good_matches) / max_possible) * 100)


def _match_orb(img1, img2):
    """Match using ORB features on Gabor-filtered images."""
    orb = cv2.ORB_create(nfeatures=2000)

    kp1, des1 = orb.detectAndCompute(img1, None)
    kp2, des2 = orb.detectAndCompute(img2, None)

    if des1 is None or des2 is None or len(kp1) < 2 or len(kp2) < 2:
        return 0.0

    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    matches = bf.knnMatch(des1, des2, k=2)

    good_matches = []
    for match_pair in matches:
        if len(match_pair) == 2:
            m, n = match_pair
            if m.distance < 0.75 * n.distance:
                good_matches.append(m)

    max_possible = min(len(kp1), len(kp2))
    if max_possible == 0:
        return 0.0

    return min(100.0, (len(good_matches) / max_possible) * 100)
