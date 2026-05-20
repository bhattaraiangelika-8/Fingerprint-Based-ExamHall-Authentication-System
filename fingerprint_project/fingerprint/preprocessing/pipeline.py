"""
Preprocessing Pipeline — v4 Integration
─────────────────────────────────────────
Implements the proven pipeline_v4.py algorithms as a Django-integrated module.

Camera pipeline:
    region_detect -> grayscale -> aspect-pad(400x500) -> Sauvola binarise
    -> width_normalise -> orientation_field -> ridge_freq_map -> minutiae

Sensor pipeline (AS608/R503):
    grayscale -> black_bar_crop -> border_mask -> aspect-pad(400x500)
    -> Otsu binarise -> width_normalise -> orientation_field
    -> ridge_freq_map -> minutiae

Canvas: 400x500 (W×H) — aspect-preserving pad, zero geometric distortion.
Sensor (256×268 after crop) fills ~84%. Camera portrait fills ~83%.
Both sources share the same coordinate space for ECC/TPS matching.
"""

import cv2
import numpy as np
import logging
import warnings

warnings.filterwarnings('ignore')

from skimage.filters import threshold_sauvola
from skimage.morphology import skeletonize, remove_small_objects
from scipy.spatial.distance import cdist

from .region_detector import detect_and_crop_fingerprint
from .quality import assess_quality

logger = logging.getLogger('fingerprint')

# ── Shared canvas ──────────────────────────────────────────────────────────────
CANVAS_W = 400
CANVAS_H = 500
SZ = (CANVAS_W, CANVAS_H)   # (width, height) for cv2 functions

# ── v4 config ──────────────────────────────────────────────────────────────────
COH_THR     = 0.10   # coherence threshold for orientation field blocks
MID_COV_THR = 0.25   # centre coherence needed to attempt core detection


# ══════════════════════════════════════════════════════════════════════════════
#  CANVAS RESIZE
# ══════════════════════════════════════════════════════════════════════════════

def _resize_to_canvas(img, w=CANVAS_W, h=CANVAS_H):
    """
    Aspect-preserving resize + mean-fill pad to exact canvas size.

    Uniform scale ensures scale_x == scale_y — no geometric distortion.
    Padding uses the image mean so uniform regions don't bias binarisation.

    Sensor  (256×268 post-crop): fills ~84 % of 400×500 canvas.
    Camera  (portrait 3:4 crop): fills ~83 % of 400×500 canvas.
    """
    src_h, src_w = img.shape[:2]
    scale  = min(w / src_w, h / src_h)
    new_w  = max(1, int(src_w * scale))
    new_h  = max(1, int(src_h * scale))
    resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)
    fill    = int(np.mean(resized))
    canvas  = np.full((h, w), fill, dtype=np.uint8)
    x_off   = (w - new_w) // 2
    y_off   = (h - new_h) // 2
    canvas[y_off:y_off + new_h, x_off:x_off + new_w] = resized
    logger.info(
        "Resize+pad: %dx%d -> %dx%d on %dx%d (scale=%.3f offset=%d,%d fill=%d)",
        src_w, src_h, new_w, new_h, w, h, scale, x_off, y_off, fill,
    )
    return canvas


# ══════════════════════════════════════════════════════════════════════════════
#  BINARISATION  (v4 Stage 1)
# ══════════════════════════════════════════════════════════════════════════════

def _binarise_camera(img):
    """CLAHE + Gaussian + Sauvola adaptive binarisation for camera images."""
    clahe    = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    enhanced = cv2.GaussianBlur(clahe.apply(img), (5, 5), 0)
    n        = enhanced.astype(np.float32) / 255.0
    binary   = (n < threshold_sauvola(n, window_size=31, k=0.10)).astype(np.uint8) * 255
    cleaned  = (remove_small_objects(binary > 0, max_size=40) * 255).astype(np.uint8)
    ridge_px = (cleaned > 0).sum()
    logger.info("Sauvola binarise: ridge_px=%d (%.1f%%)", ridge_px, ridge_px / cleaned.size * 100)
    return enhanced, cleaned


def _binarise_sensor(img):
    """CLAHE + Otsu binarisation for sensor images."""
    clahe    = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(16, 16))
    enhanced = clahe.apply(img)
    _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    cleaned  = (remove_small_objects(binary > 0, max_size=40) * 255).astype(np.uint8)
    ridge_px = (cleaned > 0).sum()
    logger.info("Otsu binarise: ridge_px=%d (%.1f%%)", ridge_px, ridge_px / cleaned.size * 100)
    return enhanced, cleaned


# ══════════════════════════════════════════════════════════════════════════════
#  WIDTH NORMALISATION  (v4 Stage 1 cont.)
# ══════════════════════════════════════════════════════════════════════════════

def _width_normalise(binary):
    """
    Skeletonize to 1-px ridge then dilate back by 1px.
    Equalises ridge width across camera/sensor sources for fair comparison.
    Returns (skeleton_u8, width_normalised_u8).
    """
    skel   = (skeletonize(binary // 255).astype(np.uint8)) * 255
    kr     = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    b_norm = cv2.dilate(skel, kr, iterations=1)
    return skel, b_norm


# ══════════════════════════════════════════════════════════════════════════════
#  ORIENTATION FIELD  (v4 Stage 2)
# ══════════════════════════════════════════════════════════════════════════════

def orientation_field(img_u8, block=8):
    """
    Per-block ridge orientation + coherence via gradient structure tensor.

    Returns:
        OF  — orientation angles in [-π/2, π/2], shape (rows, cols)
        COH — coherence [0,1], shape (rows, cols)
    """
    h, w       = img_u8.shape
    rows, cols = h // block, w // block
    OF  = np.zeros((rows, cols), np.float32)
    COH = np.zeros((rows, cols), np.float32)
    for i in range(rows):
        for j in range(cols):
            blk = img_u8[i*block:(i+1)*block, j*block:(j+1)*block].astype(np.float64)
            gx  = cv2.Sobel(blk, cv2.CV_64F, 1, 0, ksize=3)
            gy  = cv2.Sobel(blk, cv2.CV_64F, 0, 1, ksize=3)
            Vx  = np.sum(2 * gx * gy)
            Vy  = np.sum(gx**2 - gy**2)
            OF[i, j]  = np.arctan2(Vx, Vy) / 2.0
            COH[i, j] = np.sqrt(Vx**2 + Vy**2) / (np.sum(gx**2 + gy**2) + 1e-8)
    return OF, COH


def fingerprint_roi(binary):
    """Tight bounding box around the actual ridge region."""
    ys, xs = np.where(binary > 0)
    if not len(xs):
        return 0, 0, binary.shape[1], binary.shape[0]
    pad = 20
    x0 = max(0, xs.min() - pad);  x1 = min(binary.shape[1], xs.max() + pad)
    y0 = max(0, ys.min() - pad);  y1 = min(binary.shape[0], ys.max() + pad)
    return x0, y0, x1, y1


def dominant_orientation(O, C, binary_norm, block=8, coh_thr=COH_THR, min_ridge_px=8):
    """Weighted circular mean of orientation across foreground coherent blocks."""
    h, w = binary_norm.shape
    rows, cols = h // block, w // block
    angles, weights = [], []
    for i in range(rows):
        for j in range(cols):
            # MUST have actual ridge pixels, not just coherent gradients
            blk = binary_norm[i*block:(i+1)*block, j*block:(j+1)*block]
            if (blk > 0).sum() < min_ridge_px:
                continue           # skip background blocks entirely
            if C[i, j] < coh_thr:
                continue
            angles.append(O[i, j])
            weights.append(C[i, j])
    if not angles:
        return 0.0
    a = np.array(angles); w = np.array(weights)
    return np.arctan2(np.sum(w*np.cos(2*a)), np.sum(w*np.sin(2*a))) / 2.0



# ══════════════════════════════════════════════════════════════════════════════
#  RIDGE FREQUENCY  (v4 Stage 3)
# ══════════════════════════════════════════════════════════════════════════════

def median_ridge_frequency(binary, block=16):
    """Global median ridge frequency via projection profile peak spacing."""
    h, w  = binary.shape
    freqs = []
    for i in range(0, h - block, block):
        for j in range(0, w - block, block):
            blk   = binary[i:i+block, j:j+block]
            proj  = blk.sum(axis=1).astype(np.float32)
            peaks = [k for k in range(1, len(proj)-1)
                     if proj[k] > proj[k-1] and proj[k] > proj[k+1] and proj[k] > 5]
            if len(peaks) >= 2:
                freqs.append(1.0 / max(float(np.median(np.diff(peaks))), 1))
    return float(np.median(freqs)) if freqs else 0.0


def ridge_frequency_map(binary_u8, block=16):
    """Per-block ridge frequency map — shape (rows, cols)."""
    h, w       = binary_u8.shape
    rows, cols = h // block, w // block
    F = np.zeros((rows, cols), np.float32)
    for i in range(rows):
        for j in range(cols):
            blk   = binary_u8[i*block:(i+1)*block, j*block:(j+1)*block]
            proj  = blk.sum(axis=1).astype(np.float32)
            peaks = [k for k in range(1, len(proj)-1)
                     if proj[k] > proj[k-1] and proj[k] > proj[k+1] and proj[k] > 5]
            if len(peaks) >= 2:
                F[i, j] = 1.0 / max(float(np.median(np.diff(peaks))), 1)
    return F


# ══════════════════════════════════════════════════════════════════════════════
#  POINCARÉ CORE DETECTION  (v4 Stage 4)
# ══════════════════════════════════════════════════════════════════════════════

def core_coverage_check(C):
    """Mean coherence in central quarter — proxy for core visibility."""
    rows, cols = C.shape
    center     = C[rows//4:3*rows//4, cols//4:3*cols//4]
    return float(center.mean())


def poincare_best_core(O, C, binary_norm, block=8, coh_thr=0.15):
    """
    Find single most reliable core point (Poincaré index ≈ +1).
    Density-based: point with most candidate cores within 40 px radius.
    Returns (x_pixel, y_pixel) or None.
    """
    rows, cols = O.shape
    h, w = binary_norm.shape
    candidates = []
    for i in range(1, rows - 1):
        for j in range(1, cols - 1):
            if C[i-1:i+2, j-1:j+2].mean() < coh_thr:
                continue

            # Add inside the candidate loop — require actual ridge pixels at candidate location
            blk_px = binary_norm[max(0,(i-1)*block):min(h,(i+2)*block),
                                 max(0,(j-1)*block):min(w,(j+2)*block)]
            if (blk_px > 0).sum() < block * block * 0.3:   # need 30% ridge coverage
                continue

            angles = [O[r, c] for r, c in
                      [(i-1,j-1),(i-1,j),(i-1,j+1),(i,j+1),
                       (i+1,j+1),(i+1,j),(i+1,j-1),(i,j-1)]]
            diffs  = [(angles[(k+1)%8]-angles[k]+np.pi/2) % np.pi - np.pi/2
                      for k in range(8)]
            if abs(sum(diffs) / np.pi - 1) < 0.3:
                candidates.append((j*block + block//2, i*block + block//2))
    if not candidates:
        return None
    pts     = np.array(candidates, float)
    D       = cdist(pts, pts)
    density = [(D[k] < 40).sum() for k in range(len(pts))]
    return tuple(pts[np.argmax(density)].astype(int))



def ridge_centroid(img):
    """Centroid of all ridge pixels — L3 fallback anchor."""
    ys, xs = np.where(img > 0)
    if not len(xs):
        return SZ[0] // 2, SZ[1] // 2
    return int(xs.mean()), int(ys.mean())


def curvature_flow_center(O, C, block=8, coh_thr=0.1):
    """Estimate approximate core from orientation curvature (L2 fallback)."""
    rows, cols = O.shape
    best_score, best_pos = -1, (cols // 2, rows // 2)
    for i in range(1, rows - 1):
        for j in range(1, cols - 1):
            if C[i, j] < coh_thr:
                continue
            patch  = O[i-1:i+2, j-1:j+2]
            diffs  = np.abs(np.diff(patch.flatten()))
            score  = float(np.sum(np.minimum(diffs, np.pi - diffs)))
            if score > best_score:
                best_score = score
                best_pos   = (j*block + block//2, i*block + block//2)
    return best_pos


# ══════════════════════════════════════════════════════════════════════════════
#  MINUTIAE EXTRACTION  (v4 Stage 8)
# ══════════════════════════════════════════════════════════════════════════════

def _crossing_number(patch):
    p = [int(patch[r, c]) for r, c in
         [(0,1),(0,2),(1,2),(2,2),(2,1),(2,0),(1,0),(0,0)]]
    return sum(abs(p[i] - p[(i+1)%8]) for i in range(8)) // 2


def extract_oriented_minutiae(skel_u8, OF, block=8, margin=20):
    """
    Extract crossing-number minutiae with local ridge orientation angle.

    Returns list of dicts: {'x', 'y', 'type' ('end'|'bif'), 'angle'}
    """
    s = skel_u8 // 255
    h, w = s.shape
    pts  = []
    for y in range(margin, h - margin):
        for x in range(margin, w - margin):
            if s[y, x]:
                cn = _crossing_number(s[y-1:y+2, x-1:x+2])
                if cn in (1, 3):
                    oi = min(y // block, OF.shape[0] - 1)
                    oj = min(x // block, OF.shape[1] - 1)
                    pts.append({
                        'x'    : x,
                        'y'    : y,
                        'type' : 'end' if cn == 1 else 'bif',
                        'angle': float(OF[oi, oj]),
                    })
    return pts


# ══════════════════════════════════════════════════════════════════════════════
#  SENSOR ARTIFACT HELPERS  (preserved from original pipeline)
# ══════════════════════════════════════════════════════════════════════════════

def _crop_sensor_black_top(image):
    """
    Remove the black/gray artifact band at the top of AS608 sensor images.
    Uses a fixed crop of the top 30 rows since the sensor's top bezel/artifact region is constant.
    """
    h = image.shape[0]
    crop_rows = 30
    if h > crop_rows:
        logger.info("Sensor: cropped top %d rows containing border noise/artifacts", crop_rows)
        return image[crop_rows:, :]
    return image


def _mask_sensor_borders(image, border_px=8):
    """Neutralise noisy side-border columns by filling with image mean."""
    result = image.copy()
    fill   = int(np.mean(image))
    result[:, :border_px]  = fill
    result[:, -border_px:] = fill
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  PIPELINE RESULT CONTAINER
# ══════════════════════════════════════════════════════════════════════════════

class PreprocessingResult:
    """
    Container for the full v4 pipeline output.

    Attributes:
        processed_image   — binarised + width-normalised image (H×W uint8)
        skeleton          — 1-px skeleton (H×W uint8)
        orientation_field — OF angle map, shape (rows, cols)
        coherence         — coherence map,  shape (rows, cols)
        minutiae          — list of {'x','y','type','angle'} dicts
        ridge_freq_map    — per-block ridge frequency, shape (rows, cols)
        quality_result    — QualityResult from quality.py
        steps_completed   — list[str]
        fill_ratio        — fraction of ridge pixels in processed_image
        image_size        — 'WxH' string, e.g. '400x500'
    """

    def __init__(self, processed_image, skeleton, orientation_field, coherence,
                 minutiae, ridge_freq_map, quality_result, steps_completed,
                 fill_ratio=1.0):
        self.processed_image   = processed_image
        self.skeleton          = skeleton
        self.orientation_field = orientation_field
        self.coherence         = coherence
        self.minutiae          = minutiae
        self.ridge_freq_map    = ridge_freq_map
        self.quality_result    = quality_result
        self.steps_completed   = steps_completed
        self.fill_ratio        = fill_ratio
        H, W                   = processed_image.shape[:2]
        self.image_size        = f"{W}x{H}"   # WxH for reshape: (H,W)

    @property
    def minutiae_data(self):
        # Convert internal format ('end' | 'bif') to ('ending' | 'bifurcation') for testing.py
        pts = []
        for m in self.minutiae:
            pts.append({
                'x': m['x'],
                'y': m['y'],
                'type': 'ending' if m['type'] == 'end' else 'bifurcation',
                'angle': m['angle']
            })
        return {
            'minutiae_points': pts,
            'singularities_points': [],
            'normalized_img': self.processed_image,
            'thin_image': self.skeleton,
            'orientation_img': None,
            'segmented_img': None,
            'gabor_img': None,
            'minutias_img': None,
            'singularities_img': None,
        }

    def to_dict(self):
        return {
            'quality'         : self.quality_result.to_dict(),
            'steps_completed' : self.steps_completed,
            'image_shape'     : list(self.processed_image.shape),
            'image_size'      : self.image_size,
            'fill_ratio'      : round(self.fill_ratio, 3),
            'minutiae_count'  : len(self.minutiae),
        }



# ══════════════════════════════════════════════════════════════════════════════
#  SHARED PIPELINE CORE
# ══════════════════════════════════════════════════════════════════════════════

def _run_pipeline_core(binary_canvas, label='image'):
    """
    Run the v4 core stages on an already-binarised canvas image.

    Stages: width_normalise -> orientation_field -> ridge_freq_map -> minutiae

    Returns:
        (skel, b_norm, OF, COH, minutiae, freq_map)
    """
    logger.info("%s: width normalisation", label)
    skel, b_norm = _width_normalise(binary_canvas)

    logger.info("%s: orientation field", label)
    OF, COH = orientation_field(b_norm)

    logger.info("%s: ridge frequency map", label)
    freq_map = ridge_frequency_map(b_norm)

    logger.info("%s: oriented minutiae extraction", label)
    minutiae = extract_oriented_minutiae(skel, OF)

    logger.info("%s: %d minutiae extracted", label, len(minutiae))
    return skel, b_norm, OF, COH, minutiae, freq_map


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINTS
# ══════════════════════════════════════════════════════════════════════════════

def preprocess_camera_image(image_array):
    """
    Full preprocessing pipeline for camera-captured fingerprint photos.

    Pipeline:
        1. Region detection & crop  (skin/contrast/edge detection)
        2. Grayscale + aspect-preserving resize + pad  -> 400×500
        3. Sauvola adaptive binarisation
        4. Width normalisation (skeleton + 1-px dilate)
        5. Orientation field + coherence
        6. Ridge frequency map
        7. Oriented minutiae extraction (crossing number + local angle)
        8. Quality assessment

    Args:
        image_array: numpy array (BGR or grayscale)

    Returns:
        PreprocessingResult
    """
    steps = []

    # Step 1 — region detection
    logger.info("Camera Step 1: fingerprint region detection")
    cropped = detect_and_crop_fingerprint(image_array)
    steps.append('region_detection')

    # Step 2 — grayscale + canvas
    logger.info("Camera Step 2: grayscale + aspect-pad to %dx%d", CANVAS_W, CANVAS_H)
    gray   = cv2.cvtColor(cropped, cv2.COLOR_BGR2GRAY) if len(cropped.shape) == 3 else cropped.copy()
    canvas = _resize_to_canvas(gray)
    steps.append('resize_aspect_pad')

    # Step 3 — Sauvola binarisation
    logger.info("Camera Step 3: Sauvola binarisation")
    _, binary = _binarise_camera(canvas)
    steps.append('sauvola_binarise')

    # Steps 4-7 — v4 core
    logger.info("Camera Steps 4-7: v4 core pipeline")
    skel, b_norm, OF, COH, minutiae, freq_map = _run_pipeline_core(binary, 'camera')
    steps.extend(['width_normalise', 'orientation_field', 'ridge_frequency', 'minutiae_extraction'])

    # Step 8 — quality
    logger.info("Camera Step 8: quality assessment")
    quality    = assess_quality(b_norm)
    fill_ratio = (b_norm > 0).sum() / b_norm.size
    steps.append('quality_assessment')

    logger.info(
        "Camera done: %d minutiae, fill=%.1f%%, quality=%.1f",
        len(minutiae), fill_ratio * 100, quality.overall_score,
    )
    return PreprocessingResult(
        processed_image   = b_norm,
        skeleton          = skel,
        orientation_field = OF,
        coherence         = COH,
        minutiae          = minutiae,
        ridge_freq_map    = freq_map,
        quality_result    = quality,
        steps_completed   = steps,
        fill_ratio        = fill_ratio,
    )


def preprocess_sensor_image(image_array):
    """
    Full preprocessing pipeline for AS608/R503 sensor fingerprint images.

    Pipeline:
        1. Grayscale conversion
        2. Black bar artifact removal  (AS608 top-row artifact)
        3. Border noise masking        (AS608 side artefacts)
        4. Aspect-preserving resize + pad  -> 400×500  (zero distortion)
        5. Otsu binarisation
        6. Width normalisation (skeleton + 1-px dilate)
        7. Orientation field + coherence
        8. Ridge frequency map
        9. Oriented minutiae extraction
       10. Quality assessment

    Args:
        image_array: numpy array (grayscale or BGR)

    Returns:
        PreprocessingResult
    """
    steps = []

    # Step 1 — grayscale
    if len(image_array.shape) == 3:
        image_array = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)

    # Step 2 — black bar crop
    logger.info("Sensor Step 2: black bar artifact removal")
    image_array = _crop_sensor_black_top(image_array)
    steps.append('black_bar_crop')

    # Step 3 — border mask
    logger.info("Sensor Step 3: border noise masking")
    image_array = _mask_sensor_borders(image_array, border_px=8)
    steps.append('border_mask')

    # Step 4 — canvas (aspect-preserving — no geometric distortion)
    logger.info("Sensor Step 4: aspect-pad to %dx%d", CANVAS_W, CANVAS_H)
    canvas = _resize_to_canvas(image_array)
    steps.append('resize_aspect_pad')

    # Step 5 — Otsu binarisation
    logger.info("Sensor Step 5: Otsu binarisation")
    _, binary = _binarise_sensor(canvas)
    steps.append('otsu_binarise')

    # Steps 6-9 — v4 core
    logger.info("Sensor Steps 6-9: v4 core pipeline")
    skel, b_norm, OF, COH, minutiae, freq_map = _run_pipeline_core(binary, 'sensor')
    steps.extend(['width_normalise', 'orientation_field', 'ridge_frequency', 'minutiae_extraction'])

    # Step 10 — quality
    logger.info("Sensor Step 10: quality assessment")
    quality    = assess_quality(b_norm)
    fill_ratio = (b_norm > 0).sum() / b_norm.size
    steps.append('quality_assessment')

    logger.info(
        "Sensor done: %d minutiae, fill=%.1f%%, quality=%.1f",
        len(minutiae), fill_ratio * 100, quality.overall_score,
    )
    return PreprocessingResult(
        processed_image   = b_norm,
        skeleton          = skel,
        orientation_field = OF,
        coherence         = COH,
        minutiae          = minutiae,
        ridge_freq_map    = freq_map,
        quality_result    = quality,
        steps_completed   = steps,
        fill_ratio        = fill_ratio,
    )
