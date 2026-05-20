"""
Template Matching Module  —  v4 Registration + Fusion Pipeline
───────────────────────────────────────────────────────────────
Implements the complete pipeline_v4.py registration and scoring approach
for cross-sensor fingerprint matching (camera enrolled vs sensor probe).

Registration pipeline (Stages 2-7 of v4):
    Stage 2: Rotation estimate  — weighted circular mean of orientation field
    Stage 3: Scale estimate     — ridge frequency ratio (cam/sensor)
    Stage 4: Poincaré core      — 3-level fallback: L1 both cores,
                                  L2 camera core only, L3 centroid
    Stage 5: Geometric pre-alignment  (rot + scale + anchor)
    Stage 6: ECC affine refinement    (cv2.findTransformECC)
    Stage 7: TPS warp                 (if >= 50 matched minutiae pairs)

Scoring fusion (Stage 9 of v4):
    Minutiae proximity     35 %
    Minutiae descriptors   35 %
    Ridge frequency corr   20 %
    Ridge orientation corr 10 %

Returns MatchResult with score [0-100], verdict, confidence, alignment level.
"""

import cv2
import numpy as np
import logging

from ..preprocessing.pipeline import (
    orientation_field,
    dominant_orientation,
    median_ridge_frequency,
    ridge_frequency_map,
    poincare_best_core,
    core_coverage_check,
    ridge_centroid,
    curvature_flow_center,
    extract_oriented_minutiae,
    _width_normalise,
    fingerprint_roi,
    MID_COV_THR,
    SZ,
)

logger = logging.getLogger('fingerprint')

# ── Matching config (mirrors v4) ───────────────────────────────────────────────
MATCH_THR    = 38.0   # final score threshold
OVERLAP_WARN = 3.0    # % of frame
OVERLAP_FAIL = 1.5    # % of frame
MIN_TPS_PAIRS = 50    # min matched minutiae for TPS warp


# ══════════════════════════════════════════════════════════════════
#  RESULT CONTAINER
# ══════════════════════════════════════════════════════════════════

class MatchResult:
    """Container for match results. Public interface unchanged from v3."""

    def __init__(self, score, method='combined', matched_template_id=None,
                 threshold=None, alignment_level=None, quality_flag=None,
                 collage_png=None):
        self.score               = score
        self.method              = method
        self.matched_template_id = matched_template_id
        self._threshold          = threshold
        self.alignment_level     = alignment_level
        self.quality_flag        = quality_flag   # None | 'warn' | 'fail'
        self.collage_png         = collage_png    # bytes | None

    @property
    def is_match(self):
        thr = self._threshold if self._threshold is not None else MATCH_THR
        return self.score >= thr and self.quality_flag != 'fail'

    @property
    def interpretation(self):
        if self.score < 20:
            return 'NO_MATCH'
        elif self.score < 30:
            return 'WEAK_SIMILARITY'
        elif self.score < MATCH_THR:
            return 'POSSIBLE_MATCH'
        else:
            return 'STRONG_MATCH'

    def to_dict(self):
        return {
            'score'              : round(self.score, 2),
            'method'             : self.method,
            'is_match'           : self.is_match,
            'interpretation'     : self.interpretation,
            'matched_template_id': self.matched_template_id,
            'alignment_level'    : self.alignment_level,
            'quality_flag'       : self.quality_flag,
        }


# ══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════

def match_fingerprints(probe_result, stored_image,
                       method='combined',
                       minutiae_data1=None, minutiae_data2=None,
                       template2=None):
    """
    Match a probe fingerprint against a stored enrolled image.

    Args:
        probe_result:  PreprocessingResult from sensor pipeline  (primary)
                       OR numpy array (grayscale) for legacy calls
        stored_image:  numpy uint8 array, the stored b_norm (400×500)
        method:        ignored — always uses combined v4 pipeline
        minutiae_data1: ignored — use probe_result
        minutiae_data2: ignored — recomputed from stored_image
        template2:     FingerprintTemplate (stored minutiae, for descriptor scoring)

    Returns:
        MatchResult
    """
    from ..preprocessing.pipeline import PreprocessingResult

    # Accept either a PreprocessingResult or a raw numpy array
    if isinstance(probe_result, PreprocessingResult):
        probe = probe_result
    else:
        # Legacy: raw image passed — run sensor pipeline
        from ..preprocessing.pipeline import preprocess_sensor_image
        probe = preprocess_sensor_image(np.array(probe_result))

    # Recompute stored-image fields needed for registration
    stored_skel, stored_b_norm = _width_normalise(stored_image)
    OF2, COH2 = orientation_field(stored_b_norm)
    freq2     = median_ridge_frequency(stored_b_norm)
    rf_map2   = ridge_frequency_map(stored_b_norm)

    # Run v4 registration pipeline
    return _v4_match(
        # Probe (sensor)
        b1_norm  = probe.processed_image,
        skel1    = probe.skeleton,
        OF1      = probe.orientation_field,
        COH1     = probe.coherence,
        rf_map1  = probe.ridge_freq_map,
        minutiae1= probe.minutiae,
        # Reference (stored enrolled camera image)
        b2_norm  = stored_b_norm,
        skel2    = stored_skel,
        OF2      = OF2,
        COH2     = COH2,
        freq2    = freq2,
        rf_map2  = rf_map2,
        template2= template2,
    )


# ══════════════════════════════════════════════════════════════════
#  V4 REGISTRATION + SCORING
# ══════════════════════════════════════════════════════════════════

def _v4_match(b1_norm, skel1, OF1, COH1, rf_map1, minutiae1,
              b2_norm, skel2, OF2, COH2, freq2, rf_map2, template2=None):
    """
    Full v4 registration + fusion scoring pipeline.
    Image 1 = probe (sensor).  Image 2 = reference (stored camera).
    """
    w, h = SZ   # 400, 500

    # ── Crop to fingerprint ROI before everything ──
    roi1 = fingerprint_roi(b1_norm)
    roi2 = fingerprint_roi(b2_norm)
    
    b1_crop = b1_norm[roi1[1]:roi1[3], roi1[0]:roi1[2]]
    b2_crop = b2_norm[roi2[1]:roi2[3], roi2[0]:roi2[2]]
    
    # Run orientation field on cropped versions ONLY for registration & Poincaré
    OF1_crop, COH1_crop = orientation_field(b1_crop)
    OF2_crop, COH2_crop = orientation_field(b2_crop)

    # ── Stage 2: Rotation estimate ──────────────────────────────
    dom1    = dominant_orientation(OF1_crop, COH1_crop, b1_crop)
    dom2    = dominant_orientation(OF2_crop, COH2_crop, b2_crop)
    rot_rad = dom1 - dom2
    while rot_rad >  np.pi / 2: rot_rad -= np.pi
    while rot_rad < -np.pi / 2: rot_rad += np.pi
    
    rot_deg = float(np.degrees(rot_rad))
    rot_deg = float(np.clip(rot_deg, -45, 45))  # Clamp rotation
    rot_rad = np.radians(rot_deg)
    
    logger.info("Rotation: cam=%.1f° sensor=%.1f° -> rot=%.1f°",
                np.degrees(dom2), np.degrees(dom1), np.degrees(rot_rad))

    # ── Stage 3: Scale estimate ──────────────────────────────────
    freq1        = median_ridge_frequency(b1_norm)
    scale_factor = freq2 / freq1 if freq1 > 1e-6 else 1.0
    scale_factor = float(np.clip(scale_factor, 0.5, 2.0))   # sanity clamp
    logger.info("Scale: freq_probe=%.4f freq_stored=%.4f scale=%.4f",
                freq1, freq2, scale_factor)

    # ── Stage 4: Poincaré core detection + 3-level fallback ─────
    # Use cropped coherences for core visibility check
    mid_cov1 = core_coverage_check(COH1_crop)
    mid_cov2 = core_coverage_check(COH2_crop)
    
    core1 = poincare_best_core(OF1_crop, COH1_crop, b1_crop) if mid_cov1 > MID_COV_THR else None
    core2 = poincare_best_core(OF2_crop, COH2_crop, b2_crop) if mid_cov2 > MID_COV_THR else None

    # Map coordinates back to full image space
    if core1 is not None:
        core1 = (core1[0] + roi1[0], core1[1] + roi1[1])
    if core2 is not None:
        core2 = (core2[0] + roi2[0], core2[1] + roi2[1])

    quality_flag = None
    if core1 is not None and core2 is not None:
        alignment_level = 1
        anchor1, anchor2 = core1, core2
        logger.info("L1: both cores — core1=%s core2=%s", core1, core2)
    elif core2 is not None:
        alignment_level = 2
        x_c, y_c = curvature_flow_center(OF1_crop, COH1_crop)
        anchor1 = (x_c + roi1[0], y_c + roi1[1])
        anchor2 = core2
        quality_flag = 'warn'
        logger.info("L2: stored core only — anchor1=%s core2=%s", anchor1, anchor2)
    else:
        alignment_level = 3
        anchor1 = ridge_centroid(b1_norm)
        anchor2 = ridge_centroid(b2_norm)
        quality_flag = 'warn'
        logger.info("L3: centroid fallback — anchor1=%s anchor2=%s", anchor1, anchor2)

    # ── Stage 5: Geometric pre-alignment ────────────────────────
    cx_s, cy_s = anchor1   # probe anchor
    cx_d, cy_d = anchor2   # stored anchor
    cos_r = np.cos(-rot_rad) * scale_factor
    sin_r = np.sin(-rot_rad) * scale_factor
    tx    = cx_d - cos_r * cx_s + sin_r * cy_s
    ty    = cy_d - sin_r * cx_s - cos_r * cy_s
    M_geo = np.float32([[cos_r, -sin_r, tx],
                         [sin_r,  cos_r, ty]])

    b1_geo    = cv2.warpAffine(b1_norm, M_geo, SZ, flags=cv2.INTER_LINEAR)
    skel1_geo = cv2.warpAffine(skel1,   M_geo, SZ, flags=cv2.INTER_NEAREST)

    overlap_geo = ((b1_geo > 0) & (b2_norm > 0)).sum()
    overlap_geo_pct = overlap_geo / (w * h) * 100
    logger.info("Geo-align overlap: %.1f%%", overlap_geo_pct)

    # ── Stage 6: ECC affine sub-pixel refinement ─────────────────
    warp     = np.eye(2, 3, dtype=np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 500, 1e-7)
    ecc_ok   = False
    try:
        _, warp = cv2.findTransformECC(
            b2_norm.astype(np.float32),
            b1_geo.astype(np.float32),
            warp, cv2.MOTION_AFFINE, criteria)
        b1_aligned    = cv2.warpAffine(b1_geo,    warp, SZ,
                                        flags=cv2.INTER_LINEAR  + cv2.WARP_INVERSE_MAP)
        skel1_aligned = cv2.warpAffine(skel1_geo, warp, SZ,
                                        flags=cv2.INTER_NEAREST + cv2.WARP_INVERSE_MAP)
        ecc_ok = True
        logger.info("ECC converged: scale~%.3f tx=%.1f ty=%.1f",
                    warp[0,0], warp[0,2], warp[1,2])
    except Exception as ex:
        logger.warning("ECC failed (%s) — using geo-aligned image", ex)
        b1_aligned    = b1_geo
        skel1_aligned = skel1_geo

    overlap     = ((b1_aligned > 0) & (b2_norm > 0))
    overlap_pct = overlap.sum() / (w * h) * 100

    # ── Alignment quality gate ───────────────────────────────────
    if overlap_pct < OVERLAP_FAIL:
        quality_flag = 'fail'
        logger.warning("Alignment FAIL: overlap %.1f%% < %.1f%%", overlap_pct, OVERLAP_FAIL)
    elif overlap_pct < OVERLAP_WARN or alignment_level == 3:
        if quality_flag != 'fail':
            quality_flag = 'warn'
        logger.warning("Alignment WARN: overlap %.1f%%", overlap_pct)
    else:
        logger.info("Alignment PASS: overlap %.1f%% L%d", overlap_pct, alignment_level)

    # ── Stage 7: TPS warp ────────────────────────────────────────
    tps_applied = False
    m1_pts  = np.array([[m['x'], m['y']] for m in minutiae1], float) if minutiae1 else np.zeros((0,2))
    min2_raw = extract_oriented_minutiae(skel1_aligned,
                                         orientation_field(b1_aligned)[0])
    m2_pts  = np.array([[m['x'], m['y']] for m in min2_raw], float) if min2_raw else np.zeros((0,2))

    if len(m1_pts) >= MIN_TPS_PAIRS and len(m2_pts) >= MIN_TPS_PAIRS:
        tps_src, tps_dst = _match_for_tps(m2_pts, m1_pts)
        if len(tps_src) >= MIN_TPS_PAIRS:
            try:
                from scipy.interpolate import RBFInterpolator
                gy_g, gx_g = np.mgrid[0:h, 0:w]
                grid = np.column_stack([gx_g.ravel().astype(float),
                                        gy_g.ravel().astype(float)])
                rbf_x = RBFInterpolator(tps_src, tps_dst[:,0] - tps_src[:,0],
                                        kernel='thin_plate_spline', smoothing=1.0)
                rbf_y = RBFInterpolator(tps_src, tps_dst[:,1] - tps_src[:,1],
                                        kernel='thin_plate_spline', smoothing=1.0)
                map_x = (gx_g.astype(np.float32) - rbf_x(grid).reshape(h, w).astype(np.float32))
                map_y = (gy_g.astype(np.float32) - rbf_y(grid).reshape(h, w).astype(np.float32))
                b1_aligned    = cv2.remap(b1_aligned,    map_x, map_y, cv2.INTER_LINEAR)
                skel1_aligned = cv2.remap(skel1_aligned, map_x, map_y, cv2.INTER_NEAREST)
                tps_applied   = True
                logger.info("TPS applied: %d control pairs", len(tps_src))
            except Exception as ex:
                logger.warning("TPS failed (%s)", ex)

    # Re-extract minutiae from final aligned probe
    OF1_ali, _ = orientation_field(b1_aligned)
    min1_final  = extract_oriented_minutiae(skel1_aligned, OF1_ali)

    # ── Stage 8: Scoring ─────────────────────────────────────────
    # Get stored minutiae (from template2 or re-extract from stored skeleton)
    if template2 is not None:
        min2_final = [{'x': m.x, 'y': m.y, 'type': 'end' if m.type == 1 else 'bif',
                       'angle': m.angle} for m in template2.minutiae]
    else:
        min2_final = extract_oriented_minutiae(skel2, OF2)

    prox_sc = _proximity_score(min1_final, min2_final)
    desc_sc = _descriptor_score(
        _build_descriptors(min1_final, skel1_aligned),
        _build_descriptors(min2_final, skel2),
    )

    rf1    = ridge_frequency_map(b1_aligned.astype(np.uint8))
    valid  = (rf1 > 0) & (rf_map2 > 0)
    rf_sc  = (max(float(np.corrcoef(rf1[valid], rf_map2[valid])[0,1]) * 100, 0)
               if valid.sum() > 10 else 0.0)

    corr_of = np.corrcoef(OF1_ali.flatten(), OF2.flatten())[0,1]
    of_sc   = max(float(corr_of) * 100, 0)

    # Weighted fusion
    W = {'Minutiae proximity': 0.35, 'Minutiae descriptors': 0.35,
         'Ridge frequency': 0.20, 'Ridge orientation': 0.10}
    S = {'Minutiae proximity': prox_sc, 'Minutiae descriptors': desc_sc,
         'Ridge frequency': rf_sc, 'Ridge orientation': of_sc}
    final = sum(W[k] * S[k] for k in W)

    gap  = abs(final - MATCH_THR)
    conf = 'High' if gap > 15 else ('Medium' if gap > 7 else 'Low')
    if quality_flag == 'fail':
        conf = 'N/A — poor alignment'
    elif quality_flag == 'warn':
        conf = conf + ' (warn)'

    logger.info(
        "v4 match: prox=%.1f desc=%.1f rf=%.1f of=%.1f -> final=%.1f  "
        "L%d ecc=%s tps=%s overlap=%.1f%% flag=%s",
        prox_sc, desc_sc, rf_sc, of_sc, final,
        alignment_level, ecc_ok, tps_applied, overlap_pct, quality_flag,
    )

    # ── Visual collage ───────────────────────────────────────────────
    alignment_notes = {
        1: ["L1 — both cores found: core-to-core anchor"],
        2: ["L2 — probe core only: curvature-flow for ref",
            "⚠ Reduced confidence (ref core not visible)"],
        3: ["L3 — no cores found: ridge centroid fallback",
            "⚠ Orientation alignment uncertain"],
    }[alignment_level]

    collage_ctx = dict(
        b1_norm=b1_norm, b2_norm=b2_norm,
        b1_geo=b1_geo, skel1=skel1, skel2=skel2,
        b1_aligned=b1_aligned, skel1_aligned=skel1_aligned,
        OF1=OF1, OF1_ali=OF1_ali,
        OF2=OF2,
        rf1=rf1, rf_map2=rf_map2,
        core1=core1, core2=core2,
        dom1=dom1, dom2=dom2,
        rot_deg=rot_deg, scale_factor=scale_factor,
        overlap_pct=overlap_pct,
        ecc_ok=ecc_ok, tps_applied=tps_applied,
        alignment_level=alignment_level,
        alignment_notes=alignment_notes,
        quality_flag=quality_flag,
        min1=min1_final, min2=min2_final,
        prox_sc=prox_sc, desc_sc=desc_sc,
        rf_sc=rf_sc, of_sc=of_sc,
        final=final, W=W, S=S,
    )
    try:
        collage_bytes = generate_match_collage(**collage_ctx)
    except Exception as _ce:
        logger.warning("Collage generation failed: %s", _ce)
        collage_bytes = None

    return MatchResult(
        score           = float(np.clip(final, 0, 100)),
        method          = 'v4_combined',
        alignment_level = alignment_level,
        quality_flag    = quality_flag,
        collage_png     = collage_bytes,
    )


# ══════════════════════════════════════════════════════════════════
#  SCORING HELPERS  (ported from pipeline_v4.py)
# ══════════════════════════════════════════════════════════════════

def _match_for_tps(pts1, pts2, tol=20):
    """Proximity-based minutiae pairing for TPS control points."""
    if not len(pts1) or not len(pts2):
        return np.zeros((0,2)), np.zeros((0,2))
    src, dst, used = [], [], set()
    for pt in pts1:
        d = np.linalg.norm(pts2 - pt, axis=1)
        i = int(np.argmin(d))
        if d[i] < tol and i not in used:
            src.append(pt); dst.append(pts2[i]); used.add(i)
    return (np.array(src, float), np.array(dst, float)) if src else (np.zeros((0,2)), np.zeros((0,2)))


def _crossing_number(patch):
    p = [int(patch[r, c]) for r, c in
         [(0,1),(0,2),(1,2),(2,2),(2,1),(2,0),(1,0),(0,0)]]
    return sum(abs(p[i] - p[(i+1)%8]) for i in range(8)) // 2


def _ridge_count_between(p1, p2, skel_i, n=12):
    xs   = np.linspace(p1['x'], p2['x'], n).astype(int)
    ys   = np.linspace(p1['y'], p2['y'], n).astype(int)
    h, w = skel_i.shape
    cross, prev = 0, 0
    for xi, yi in zip(xs, ys):
        if 0 <= xi < w and 0 <= yi < h:
            cur = skel_i[yi, xi]
            if prev == 0 and cur == 1: cross += 1
            prev = cur
    return cross


def _build_descriptors(pts, skel_u8, max_pairs=600):
    """Build pairwise minutiae descriptors: (dist, dAngle, ridgeCount, typeMatch)."""
    skel_i = skel_u8 // 255
    desc   = []
    for i, p1 in enumerate(pts):
        for p2 in pts[max(0, i-20):i+20]:
            if p1 is p2: continue
            dx   = p1['x'] - p2['x']; dy = p1['y'] - p2['y']
            dist = np.sqrt(dx*dx + dy*dy)
            if dist < 8 or dist > 130: continue
            da = abs(p1['angle'] - p2['angle']); da = min(da, np.pi - da)
            rc = _ridge_count_between(p1, p2, skel_i)
            tc = 1 if p1['type'] == p2['type'] else 0
            desc.append((dist, da, rc, tc))
            if len(desc) >= max_pairs: break
        if len(desc) >= max_pairs: break
    return np.array(desc, np.float32) if desc else np.zeros((0, 4), np.float32)


def _descriptor_score(d1, d2, bins=22):
    """Histogram intersection score over descriptor dimensions."""
    if not len(d1) or not len(d2): return 0.0
    scores = []
    for c in range(4):
        v1, v2 = d1[:, c], d2[:, c]
        lo = min(v1.min(), v2.min()); hi = max(v1.max(), v2.max()) + 1e-8
        h1, _ = np.histogram(v1, bins=bins, range=(lo, hi), density=True)
        h2, _ = np.histogram(v2, bins=bins, range=(lo, hi), density=True)
        scores.append(np.sum(np.minimum(h1, h2)) / bins)
    return float(np.mean(scores)) * 100


def _proximity_score(pts1, pts2, tol=18):
    """Fraction of probe minutiae matched within tol px of a stored minutia."""
    if not pts1 or not pts2: return 0.0
    a1 = np.array([[p['x'], p['y']] for p in pts1], float)
    a2 = np.array([[p['x'], p['y']] for p in pts2], float)
    matched, used = 0, set()
    for pt in a1:
        d = np.linalg.norm(a2 - pt, axis=1)
        i = int(np.argmin(d))
        if d[i] < tol and i not in used:
            matched += 1; used.add(i)
    return matched / max(len(pts1), len(pts2)) * 100


# ══════════════════════════════════════════════════════════════════
#  LEGACY HELPERS  (kept for any remaining call-sites in views.py)
# ══════════════════════════════════════════════════════════════════

def match_multi_template(probe_image, stored_images, stored_ids=None,
                         probe_minutiae_data=None):
    """
    Match probe against multiple stored images.
    Legacy helper — views.py now calls match_fingerprints directly.
    """
    best = MatchResult(0.0, 'v4_combined')
    for i, stored_img in enumerate(stored_images):
        result   = match_fingerprints(probe_image, stored_img)
        tmpl_id  = stored_ids[i] if stored_ids and i < len(stored_ids) else i
        if result.score > best.score:
            best = MatchResult(result.score, result.method, tmpl_id,
                               alignment_level=result.alignment_level,
                               quality_flag=result.quality_flag)
    logger.info("Multi-template: best=%.2f id=%s checked=%d",
                best.score, best.matched_template_id, len(stored_images))
    return best


# ══════════════════════════════════════════════════════════════════
#  VISUAL COLLAGE  (mirrors pipeline_v4.py dashboard)
# ══════════════════════════════════════════════════════════════════

def generate_match_collage(
    b1_norm, b2_norm, b1_geo, skel1, skel2,
    b1_aligned, skel1_aligned,
    OF1, OF1_ali, OF2,
    rf1, rf_map2,
    core1, core2, dom1, dom2,
    rot_deg, scale_factor, overlap_pct,
    ecc_ok, tps_applied,
    alignment_level, alignment_notes, quality_flag,
    min1, min2,
    prox_sc, desc_sc, rf_sc, of_sc,
    final, W, S,
):
    """
    Generate a 4-row × 6-col matplotlib dashboard collage that mirrors
    the pipeline_v4.py visual output.  Returns PNG bytes (io.BytesIO).
    """
    import io
    import matplotlib
    matplotlib.use('Agg')               # non-interactive backend for Django
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    from matplotlib.patches import Patch

    # ── Colour palette (same as pipeline_v4) ───────────────────────
    BG   = '#0d0d1a'
    PNL  = '#12122a'
    AC   = '#4fc3f7'
    WT   = '#e8e8ff'
    MC   = '#00e676' if final >= MATCH_THR else '#ff1744'
    WARN_C = '#ffb74d'

    fig = plt.figure(figsize=(26, 20), facecolor=BG)
    fig.suptitle(
        'Cross-Sensor Fingerprint Matching — v4  '
        '(Rotation + Scale + Poincaré + ECC + TPS)',
        fontsize=19, color=WT, fontweight='bold', y=0.999,
    )
    gs = gridspec.GridSpec(
        4, 6, figure=fig,
        hspace=0.50, wspace=0.28,
        left=0.03, right=0.97, top=0.963, bottom=0.04,
    )

    def iax(ax, img, title, cmap='gray', vmin=None, vmax=None):
        ax.imshow(img, cmap=cmap, aspect='auto', vmin=vmin, vmax=vmax)
        ax.set_title(title, color=AC, fontsize=8, pad=4, fontweight='bold')
        ax.axis('off')
        ax.set_facecolor(PNL)

    # ── Row 0: binarised images + orientation arrows ────────────────
    r0 = [fig.add_subplot(gs[0, i]) for i in range(6)]
    iax(r0[0], b1_norm, 'Probe (sensor) — binarised')
    iax(r0[1], b2_norm, 'Reference (camera) — binarised')

    # Overlay overlay (before alignment)
    ov_raw = np.zeros((*b1_norm.shape, 3), np.uint8)
    ov_raw[b1_norm > 0] = [0, 180, 255]
    ov_raw[b2_norm > 0] = [255, 120, 0]
    ov_raw[(b1_norm > 0) & (b2_norm > 0)] = [0, 240, 100]
    iax(r0[2], ov_raw, 'Pre-align overlay  ■probe ■ref ■both', cmap=None)

    # Probe orientation arrow + core
    r0[3].imshow(b1_norm, cmap='gray', aspect='auto')
    r0[3].axis('off'); r0[3].set_facecolor(PNL)
    r0[3].set_title(f'Probe OF  dom={np.degrees(dom1):.1f}°',
                    color=AC, fontsize=8, pad=4, fontweight='bold')
    cx, cy = b1_norm.shape[1] // 2, b1_norm.shape[0] // 2
    dx = np.cos(dom1) * 60;  dy = np.sin(dom1) * 60
    r0[3].annotate('', xy=(cx+dx, cy+dy), xytext=(cx-dx, cy-dy),
                   arrowprops=dict(arrowstyle='<->', color='yellow', lw=2))
    if core1:
        r0[3].scatter([core1[0]], [core1[1]], s=80, c='red', zorder=5, marker='*')

    # Reference orientation arrow + core
    r0[4].imshow(b2_norm, cmap='gray', aspect='auto')
    r0[4].axis('off'); r0[4].set_facecolor(PNL)
    r0[4].set_title(
        f'Reference OF  dom={np.degrees(dom2):.1f}°  '
        f'rot={rot_deg:.1f}°  scale={scale_factor:.3f}',
        color=AC, fontsize=8, pad=4, fontweight='bold',
    )
    dx2 = np.cos(dom2) * 60;  dy2 = np.sin(dom2) * 60
    r0[4].annotate('', xy=(cx+dx2, cy+dy2), xytext=(cx-dx2, cy-dy2),
                   arrowprops=dict(arrowstyle='<->', color='#ff9800', lw=2))
    if core2:
        r0[4].scatter([core2[0]], [core2[1]], s=80, c='red', zorder=5, marker='*')

    # Orientation field HSV (probe)
    of_u8 = ((OF1 + np.pi / 2) / np.pi * 255).astype(np.uint8)
    import cv2
    of_rgb = cv2.cvtColor(cv2.applyColorMap(of_u8, cv2.COLORMAP_HSV),
                          cv2.COLOR_BGR2RGB)
    iax(r0[5], of_rgb, 'Probe — orientation field (HSV)', cmap=None)

    # ── Row 1: alignment stages ─────────────────────────────────────
    r1 = [fig.add_subplot(gs[1, i]) for i in range(6)]
    iax(r1[0], b1_norm,  'Probe — width-normalised')
    iax(r1[1], b2_norm,  'Reference — before alignment')
    iax(r1[2], b1_geo,   'Probe — after rot+scale+anchor')

    ov_geo = np.zeros((*b1_norm.shape, 3), np.uint8)
    ov_geo[b1_geo > 0]  = [0, 180, 255]
    ov_geo[b2_norm > 0] = [255, 120, 0]
    ov_geo[(b1_geo > 0) & (b2_norm > 0)] = [0, 240, 100]
    iax(r1[3], ov_geo, 'Geo-align overlay', cmap=None)

    iax(r1[4], b1_aligned,
        'Probe — after ECC refinement' + (' + TPS' if tps_applied else ''))

    ov_fin = np.zeros((*b1_norm.shape, 3), np.uint8)
    ov_fin[b1_aligned > 0] = [0, 180, 255]
    ov_fin[b2_norm > 0]    = [255, 120, 0]
    ov_fin[(b1_aligned > 0) & (b2_norm > 0)] = [0, 240, 100]
    iax(r1[5], ov_fin, 'Final overlay  ■probe ■ref ■both', cmap=None)

    # ── Row 2: skeletons + minutiae + OF maps + freq maps ───────────
    r2 = [fig.add_subplot(gs[2, i]) for i in range(6)]

    # Probe skeleton + minutiae
    r2[0].imshow(skel1_aligned, cmap='gray', aspect='auto')
    r2[0].axis('off'); r2[0].set_facecolor(PNL)
    r2[0].set_title('Probe skeleton + minutiae (aligned)',
                    color=AC, fontsize=8, pad=4, fontweight='bold')
    ends1 = np.array([[m['x'], m['y']] for m in min1 if m['type'] == 'end'])
    bifs1 = np.array([[m['x'], m['y']] for m in min1 if m['type'] == 'bif'])
    if len(ends1): r2[0].scatter(ends1[:, 0], ends1[:, 1], s=4, c='cyan',    alpha=0.7, zorder=3)
    if len(bifs1): r2[0].scatter(bifs1[:, 0], bifs1[:, 1], s=4, c='#ff6b6b', alpha=0.7, zorder=3)
    if core1:
        r2[0].scatter([core1[0]], [core1[1]], s=120, c='yellow', marker='*', zorder=6,
                      label='Core')
        r2[0].legend(fontsize=7, facecolor=PNL, labelcolor=WT)

    # Reference skeleton + minutiae
    r2[1].imshow(skel2, cmap='gray', aspect='auto')
    r2[1].axis('off'); r2[1].set_facecolor(PNL)
    r2[1].set_title('Reference skeleton + minutiae',
                    color=AC, fontsize=8, pad=4, fontweight='bold')
    ends2 = np.array([[m['x'], m['y']] for m in min2 if m['type'] == 'end'])
    bifs2 = np.array([[m['x'], m['y']] for m in min2 if m['type'] == 'bif'])
    if len(ends2): r2[1].scatter(ends2[:, 0], ends2[:, 1], s=4, c='cyan',    alpha=0.7, zorder=3)
    if len(bifs2): r2[1].scatter(bifs2[:, 0], bifs2[:, 1], s=4, c='#ff6b6b', alpha=0.7, zorder=3)
    if core2:
        r2[1].scatter([core2[0]], [core2[1]], s=120, c='yellow', marker='*', zorder=6)

    # Orientation fields
    of1_u8 = ((OF1_ali + np.pi / 2) / np.pi * 255).astype(np.uint8)
    of1_rgb = cv2.cvtColor(cv2.applyColorMap(of1_u8, cv2.COLORMAP_HSV), cv2.COLOR_BGR2RGB)
    iax(r2[2], of1_rgb, 'Orientation field — Probe (aligned)', cmap=None)

    of2_u8 = ((OF2 + np.pi / 2) / np.pi * 255).astype(np.uint8)
    of2_rgb = cv2.cvtColor(cv2.applyColorMap(of2_u8, cv2.COLORMAP_HSV), cv2.COLOR_BGR2RGB)
    iax(r2[3], of2_rgb, 'Orientation field — Reference', cmap=None)

    # Ridge frequency maps
    iax(r2[4], rf1,     'Ridge freq map — Probe (aligned)', cmap='plasma')
    iax(r2[5], rf_map2, 'Ridge freq map — Reference',       cmap='plasma')

    # ── Row 3: alignment log + descriptor hist + score bars + verdict
    r3 = [fig.add_subplot(gs[3, i]) for i in range(6)]

    # Alignment info panel
    ax_info = r3[0]; ax_info.set_facecolor(PNL); ax_info.axis('off')
    for sp in ax_info.spines.values(): sp.set_color(WARN_C)
    ax_info.set_title('Alignment log', color=AC, fontsize=8, pad=4, fontweight='bold')
    level_col = {'1': '#00e676', '2': '#ffb74d', '3': '#ff1744'}[str(alignment_level)]
    ax_info.text(0.5, 0.93, f'Level L{alignment_level}',
                 ha='center', va='top', transform=ax_info.transAxes,
                 fontsize=13, color=level_col, fontweight='bold')
    info_lines = [
        f"rot={rot_deg:.1f}°  scale={scale_factor:.3f}",
        f"Core probe: {'✓ ' + str(core1) if core1 else '✗ not found'}",
        f"Core ref:   {'✓ ' + str(core2) if core2 else '✗ not found'}",
        f"Overlap: {overlap_pct:.1f}%",
        f"ECC: {'✓' if ecc_ok else '✗'}  TPS: {'✓' if tps_applied else '—'}",
        f"Quality: {(quality_flag or 'PASS').upper()}",
    ]
    for idx, line in enumerate(info_lines):
        col = WT if 'Quality' not in line else WARN_C
        ax_info.text(0.5, 0.76 - idx * 0.12, line,
                     ha='center', va='top', transform=ax_info.transAxes,
                     fontsize=8, color=col)

    # Descriptor distributions histogram
    r3[1].set_facecolor(PNL)
    r3[1].set_title('Minutiae descriptor distributions',
                    color=AC, fontsize=8, pad=4, fontweight='bold')
    col_names = ['Distance', 'Δ Angle', 'Ridge count', 'Type']
    pal       = ['#4fc3f7', '#81c784', '#ffb74d', '#ce93d8']
    desc1 = _build_descriptors(min1, skel1_aligned)
    desc2 = _build_descriptors(min2, skel2)
    if len(desc1) and len(desc2):
        for ci, (cn_, cc) in enumerate(zip(col_names, pal)):
            v1, v2 = desc1[:, ci], desc2[:, ci]
            lo = min(v1.min(), v2.min()); hi = max(v1.max(), v2.max()) + 1e-8
            bins = np.linspace(lo, hi, 20); bc = (bins[:-1] + bins[1:]) / 2
            h1, _ = np.histogram(v1, bins=bins, density=True)
            h2, _ = np.histogram(v2, bins=bins, density=True)
            r3[1].plot(bc, h1, color=cc, lw=1.3, label=f'P {cn_}',  alpha=0.95)
            r3[1].plot(bc, h2, color=cc, lw=1.3, ls='--', label=f'R {cn_}', alpha=0.6)
    r3[1].tick_params(colors=WT, labelsize=7)
    for sp in r3[1].spines.values(): sp.set_color('#2a2a4a')
    r3[1].legend(fontsize=6, facecolor=PNL, labelcolor=WT, ncol=2, loc='upper right')

    # Score bars
    ax_bar = r3[2]; ax_bar.set_facecolor(PNL)
    labels = [f"{k}  (×{W[k]})" for k in W] + ['FINAL SCORE']
    vals   = [S[k] for k in W] + [final]
    cols_b = ['#ffb74d', '#81c784', '#4fc3f7', '#ce93d8', MC]
    bars_h = ax_bar.barh(labels, vals, color=cols_b,
                         edgecolor='#1a1a2e', linewidth=0.7, height=0.55)
    ax_bar.axvline(MATCH_THR, color='yellow', ls='--', lw=2,
                   label=f'Threshold ({MATCH_THR}%)')
    ax_bar.set_xlim(0, 110)
    for bar, v in zip(bars_h, vals):
        ax_bar.text(v + 1, bar.get_y() + bar.get_height() / 2,
                    f'{v:.1f}%', va='center', color=WT, fontsize=9, fontweight='bold')
    ax_bar.tick_params(colors=WT, labelsize=8)
    for sp in ax_bar.spines.values(): sp.set_color('#2a2a4a')
    ax_bar.set_xlabel('Score (%)', color=WT, fontsize=9)
    ax_bar.set_title('Fusion scores — identity-level features',
                     color=WT, fontsize=9, pad=4)
    ax_bar.legend(fontsize=8, facecolor=PNL, labelcolor=WT, loc='lower right')

    # Verdict panel
    match = final >= MATCH_THR and quality_flag != 'fail'
    verdict = ('✔ MATCH' if match else '✘ NO MATCH')
    gap  = abs(final - MATCH_THR)
    conf = 'High' if gap > 15 else ('Medium' if gap > 7 else 'Low')
    if quality_flag == 'fail':
        conf = 'N/A — poor alignment'
    elif quality_flag == 'warn':
        conf += ' (warn)'

    ax_v = r3[3]; ax_v.set_facecolor('#0d2a1a' if match else '#2a0d0d')
    for sp in ax_v.spines.values(): sp.set_edgecolor(MC); sp.set_linewidth(3)
    ax_v.text(0.5, 0.86, '✔' if match else '✘',
              ha='center', va='center', fontsize=48, color=MC,
              transform=ax_v.transAxes, fontweight='bold')
    ax_v.text(0.5, 0.68, verdict,
              ha='center', va='center', fontsize=17, color=MC,
              transform=ax_v.transAxes, fontweight='bold')
    ax_v.text(0.5, 0.54, f'Score: {final:.1f}%',
              ha='center', va='center', fontsize=13, color=WT,
              transform=ax_v.transAxes)
    ax_v.text(0.5, 0.42, f'Confidence: {conf}',
              ha='center', va='center', fontsize=11, color='#aaa',
              transform=ax_v.transAxes)
    ax_v.text(0.5, 0.30,
              f'Alignment: L{alignment_level}  {"TPS ✓" if tps_applied else "TPS —"}',
              ha='center', va='center', fontsize=9, color='#888',
              transform=ax_v.transAxes)
    ax_v.text(0.5, 0.20, f'rot={rot_deg:.1f}°  scale={scale_factor:.3f}',
              ha='center', va='center', fontsize=9, color='#888',
              transform=ax_v.transAxes)
    ax_v.text(0.5, 0.10,
              f'overlap={overlap_pct:.1f}%  min={len(min1)}vs{len(min2)}',
              ha='center', va='center', fontsize=8, color='#555',
              transform=ax_v.transAxes)
    ax_v.set_xticks([]); ax_v.set_yticks([])
    ax_v.set_title('VERDICT', color=WT, fontsize=11, fontweight='bold')

    # Quality gate panel
    ax_q = r3[4]; ax_q.set_facecolor(PNL)
    for sp in ax_q.spines.values(): sp.set_edgecolor(WARN_C); sp.set_linewidth(2)
    ax_q.axis('off')
    ax_q.set_title('Quality gate', color=AC, fontsize=8, pad=4, fontweight='bold')
    qtext = {
        'warn': '⚠ WARNING\nAlignment limited\nCore not fully visible\nProceed with caution',
        'fail': '❌ FAILED\nOverlap too low\nPlease provide a\nbetter sensor image',
        None  : '✅ PASSED\nAlignment verified\nCore detected\nOverlap sufficient',
    }[quality_flag]
    ax_q.text(0.5, 0.55, qtext,
              ha='center', va='center', transform=ax_q.transAxes,
              fontsize=11, color=WARN_C, fontweight='bold',
              bbox=dict(boxstyle='round,pad=0.5', facecolor='#0d0d1a',
                        edgecolor=WARN_C, linewidth=1.5))

    # Alignment notes panel
    ax_n = r3[5]; ax_n.set_facecolor(PNL); ax_n.axis('off')
    ax_n.set_title('Alignment notes', color=AC, fontsize=8, pad=4, fontweight='bold')
    for ni, note in enumerate(alignment_notes):
        ax_n.text(0.5, 0.80 - ni * 0.18, note,
                  ha='center', va='top', transform=ax_n.transAxes,
                  fontsize=9, color=WARN_C if '⚠' in note else WT,
                  fontweight='bold')

    # Global legend
    fig.legend(
        handles=[
            Patch(facecolor='cyan',    label='Ridge endings'),
            Patch(facecolor='#ff6b6b', label='Bifurcations'),
            Patch(facecolor='yellow',  label='★ Core point'),
            Patch(facecolor='#00b4ff', label='Probe ridges'),
            Patch(facecolor='#ff7800', label='Reference ridges'),
            Patch(facecolor='#00f064', label='Overlap region'),
        ],
        loc='lower center', ncol=6, fontsize=8,
        facecolor=PNL, labelcolor=WT, framealpha=0.9,
        bbox_to_anchor=(0.5, 0.0),
    )

    buf = io.BytesIO()
    plt.savefig(buf, dpi=130, bbox_inches='tight', facecolor=BG, format='png')
    plt.close(fig)
    buf.seek(0)
    return buf.read()

