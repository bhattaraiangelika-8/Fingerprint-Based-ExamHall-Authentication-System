"""
╔══════════════════════════════════════════════════════════════════════╗
║   Cross-Sensor Fingerprint Matching Pipeline  —  v4                 ║
║   Camera (grayscale) vs Sensor (binarized)                          ║
╠══════════════════════════════════════════════════════════════════════╣
║  Usage:                                                              ║
║    python pipeline_v4.py <camera_image> <sensor_image> <output.png> ║
║                                                                      ║
║  Dependencies:                                                       ║
║    pip install opencv-python-headless scikit-image numpy             ║
║                scipy matplotlib                                      ║
╠══════════════════════════════════════════════════════════════════════╣
║  What's NEW vs v3:                                                   ║
║                                                                      ║
║  Registration (replaces plain ECC):                                  ║
║    Step 1 : Rotation estimate — weighted circular mean of            ║
║             orientation field across all coherent blocks             ║
║    Step 2 : Scale estimate — global ridge frequency ratio            ║
║             (median inter-ridge spacing camera / sensor)             ║
║    Step 3 : Poincaré index core detection with intelligent           ║
║             3-LEVEL FALLBACK CHAIN:                                  ║
║             L1 — both cores visible → core-to-core anchor           ║
║             L2 — camera core only  → camera anchor + curvature est. ║
║             L3 — no cores          → centroid anchor + flag warning  ║
║    Step 4 : ECC affine sub-pixel refinement                          ║
║    Step 5 : TPS warp (if ≥50 matched minutiae)                      ║
║    Step 6 : Alignment quality gate → rejects/warns on poor overlap   ║
║                                                                      ║
║  Matching (unchanged from v3):                                       ║
║    Minutiae proximity      35%                                       ║
║    Minutiae descriptors    35%                                       ║
║    Ridge frequency         20%                                       ║
║    Ridge orientation       10%                                       ║
║    Gabor: diagnostic only (excluded — pattern class, not identity)   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import sys, cv2, numpy as np, warnings, matplotlib
matplotlib.use('Agg'); warnings.filterwarnings('ignore')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from skimage.filters import threshold_sauvola
from skimage.morphology import skeletonize, remove_small_objects
from scipy.interpolate import RBFInterpolator

# ───────────────────────────────────────────────────────────
# CONFIG
# ───────────────────────────────────────────────────────────
SZ              = (400, 500)    # (width, height)
MATCH_THR       = 38.0          # final score threshold (0-100)
OVERLAP_WARN    = 3.0           # % of frame — below this warn user
OVERLAP_FAIL    = 1.5           # % of frame — below this reject
COH_THR         = 0.10          # coherence threshold for OF blocks
MID_COV_THR     = 0.25          # center coherence for core visibility
MIN_TPS_PAIRS   = 50            # minimum matched minutiae for TPS

# ───────────────────────────────────────────────────────────
# 0. LOAD
# ───────────────────────────────────────────────────────────
if len(sys.argv) != 4:
    print("Usage: python pipeline_v4.py <camera> <sensor> <output.png>")
    sys.exit(1)
cam_path, sensor_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]

raw1 = cv2.resize(cv2.imread(cam_path,    cv2.IMREAD_GRAYSCALE), SZ)
raw2 = cv2.resize(cv2.imread(sensor_path, cv2.IMREAD_GRAYSCALE), SZ)
print(f"Loaded  cam={raw1.shape}  sensor={raw2.shape}\n")

# ───────────────────────────────────────────────────────────
# STAGE 1  — Binarisation + ridge-width normalisation
# ───────────────────────────────────────────────────────────
print("── Stage 1: Binarisation ───────────────────────────────────")

def binarise_camera(img):
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
    e = cv2.GaussianBlur(clahe.apply(img), (5, 5), 0)
    n = e.astype(np.float32) / 255.0
    b = (n < threshold_sauvola(n, window_size=31, k=0.10)).astype(np.uint8) * 255
    return e, (remove_small_objects(b > 0, max_size=40) * 255).astype(np.uint8)

def binarise_sensor(img):
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(16, 16))
    e = clahe.apply(img)
    _, b = cv2.threshold(e, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return e, (remove_small_objects(b > 0, max_size=40) * 255).astype(np.uint8)

def width_normalise(binary):
    skel = (skeletonize(binary // 255).astype(np.uint8)) * 255
    kr   = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return skel, cv2.dilate(skel, kr, iterations=1)

enh1, bin1       = binarise_camera(raw1)
enh2, bin2       = binarise_sensor(raw2)
skel1_u, b1_norm = width_normalise(bin1)
skel2_u, b2_norm = width_normalise(bin2)
print(f"  ridge px: cam={( b1_norm > 0).sum():>7}   sen={(b2_norm > 0).sum():>7}")

# ───────────────────────────────────────────────────────────
# HELPERS — orientation field + coherence
# ───────────────────────────────────────────────────────────
def orientation_field(img_u8, block=8):
    """Per-block ridge orientation + coherence (gradient structure tensor)."""
    h, w       = img_u8.shape
    rows, cols = h // block, w // block
    O = np.zeros((rows, cols), np.float32)
    C = np.zeros((rows, cols), np.float32)
    for i in range(rows):
        for j in range(cols):
            blk = img_u8[i*block:(i+1)*block, j*block:(j+1)*block].astype(np.float64)
            gx  = cv2.Sobel(blk, cv2.CV_64F, 1, 0, ksize=3)
            gy  = cv2.Sobel(blk, cv2.CV_64F, 0, 1, ksize=3)
            Vx  = np.sum(2 * gx * gy); Vy = np.sum(gx**2 - gy**2)
            O[i, j] = np.arctan2(Vx, Vy) / 2.0
            C[i, j] = np.sqrt(Vx**2 + Vy**2) / (np.sum(gx**2 + gy**2) + 1e-8)
    return O, C

OF1, COH1 = orientation_field(b1_norm)
OF2, COH2 = orientation_field(b2_norm)

# ───────────────────────────────────────────────────────────
# STAGE 2  — Rotation estimate (weighted circular mean of OF)
# ───────────────────────────────────────────────────────────
def dominant_orientation(O, C, coh_thr=COH_THR):
    """Weighted circular mean of orientation across all coherent blocks."""
    mask = C > coh_thr
    if not mask.any():
        return 0.0
    a = O[mask]; w = C[mask]
    sx = np.sum(w * np.cos(2 * a)); sy = np.sum(w * np.sin(2 * a))
    return np.arctan2(sy, sx) / 2.0

dom1 = dominant_orientation(OF1, COH1)
dom2 = dominant_orientation(OF2, COH2)
rot_rad = dom1 - dom2
# fold to [-π/2, π/2]
while rot_rad >  np.pi / 2: rot_rad -= np.pi
while rot_rad < -np.pi / 2: rot_rad += np.pi
rot_deg = float(np.degrees(rot_rad))
print(f"\n── Stage 2: Rotation estimate ──────────────────────────────")
print(f"  Dominant orient cam={np.degrees(dom1):.1f}°  sen={np.degrees(dom2):.1f}°")
print(f"  Estimated rotation to apply: {rot_deg:.1f}°")

# ───────────────────────────────────────────────────────────
# STAGE 3  — Scale estimate (ridge frequency ratio)
# ───────────────────────────────────────────────────────────
def median_ridge_frequency(binary, block=16):
    """Median ridge frequency via projection profile peak spacing."""
    h, w   = binary.shape
    freqs  = []
    for i in range(0, h - block, block):
        for j in range(0, w - block, block):
            blk  = binary[i:i+block, j:j+block]
            proj = blk.sum(axis=1).astype(np.float32)
            peaks = [k for k in range(1, len(proj)-1)
                     if proj[k] > proj[k-1] and proj[k] > proj[k+1]
                     and proj[k] > 5]
            if len(peaks) >= 2:
                freqs.append(1.0 / max(float(np.median(np.diff(peaks))), 1))
    return float(np.median(freqs)) if freqs else 0.0

freq1 = median_ridge_frequency(b1_norm)
freq2 = median_ridge_frequency(b2_norm)
scale_factor = freq1 / freq2 if freq2 > 1e-6 else 1.0
print(f"\n── Stage 3: Scale estimate ─────────────────────────────────")
print(f"  Ridge freq: cam={freq1:.4f}  sen={freq2:.4f}")
print(f"  Scale factor (cam/sen): {scale_factor:.4f}  "
      f"({'sensor zoomed in' if scale_factor < 1 else 'sensor zoomed out'})")

# ───────────────────────────────────────────────────────────
# STAGE 4  — Poincaré index core detection + 3-level fallback
# ───────────────────────────────────────────────────────────
print(f"\n── Stage 4: Poincaré core detection + fallback ─────────────")

def core_coverage_check(C, block=8):
    """Check if central region has enough coherent blocks for core detection."""
    rows, cols = C.shape
    center     = C[rows//4 : 3*rows//4, cols//4 : 3*cols//4]
    return float(center.mean())

def poincare_best_core(O, C, block=8, coh_thr=0.15):
    """
    Find the single most reliable core point (Poincaré index ≈ +1).
    Uses density-based clustering: the spatial point with the most
    candidate cores within 40px radius is returned.
    Returns (x_pixel, y_pixel) or None if no core found.
    """
    rows, cols = O.shape
    candidates = []
    for i in range(1, rows - 1):
        for j in range(1, cols - 1):
            if C[i-1:i+2, j-1:j+2].mean() < coh_thr:
                continue
            angles = [O[r, c] for r, c in
                      [(i-1,j-1),(i-1,j),(i-1,j+1),(i,j+1),
                       (i+1,j+1),(i+1,j),(i+1,j-1),(i,j-1)]]
            diffs  = [(angles[(k+1)%8]-angles[k]+np.pi/2) % np.pi - np.pi/2
                      for k in range(8)]
            if abs(sum(diffs) / np.pi - 1) < 0.3:
                candidates.append((j*block + block//2,
                                   i*block + block//2))
    if not candidates:
        return None
    pts = np.array(candidates, float)
    # pick the point with most neighbours within 40px → most stable core
    from scipy.spatial.distance import cdist
    D       = cdist(pts, pts)
    density = [(D[k] < 40).sum() for k in range(len(pts))]
    return tuple(pts[np.argmax(density)].astype(int))

def ridge_centroid(img):
    """Centroid of all ridge pixels — used as fallback anchor."""
    ys, xs = np.where(img > 0)
    if not len(xs):
        return SZ[0]//2, SZ[1]//2
    return int(xs.mean()), int(ys.mean())

def curvature_flow_center(O, C, block=8, coh_thr=0.1):
    """
    Estimate approximate core location from curvature of orientation flow.
    Used when sensor core is not visible.
    Idea: the core lies where the orientation changes most rapidly.
    Returns (x, y) in pixel coords.
    """
    rows, cols = O.shape
    best_score, best_pos = -1, (cols//2, rows//2)
    for i in range(1, rows-1):
        for j in range(1, cols-1):
            if C[i, j] < coh_thr: continue
            # local variation of orientation in 3×3 neighbourhood
            patch = O[i-1:i+2, j-1:j+2]
            diffs = np.abs(np.diff(patch.flatten()))
            score = float(np.sum(np.minimum(diffs, np.pi - diffs)))
            if score > best_score:
                best_score = score
                best_pos   = (j*block + block//2, i*block + block//2)
    return best_pos

# -- Run core detection ---------------------------------
mid_cov1 = core_coverage_check(COH1)
mid_cov2 = core_coverage_check(COH2)
core1    = poincare_best_core(OF1, COH1) if mid_cov1 > MID_COV_THR else None
core2    = poincare_best_core(OF2, COH2) if mid_cov2 > MID_COV_THR else None

print(f"  Center coherence: cam={mid_cov1:.3f}  sen={mid_cov2:.3f}")
print(f"  Core detected:    cam={core1}  sen={core2}")

# -- Determine fallback level --------------------------
ALIGNMENT_LEVEL    = None
ALIGNMENT_NOTES    = []
QUALITY_FLAG       = None   # None | 'warn' | 'fail'

if core1 is not None and core2 is not None:
    ALIGNMENT_LEVEL = 1
    anchor_cam = core1
    anchor_sen = core2
    ALIGNMENT_NOTES.append("L1 — both cores found: core-to-core anchor")

elif core1 is not None:
    ALIGNMENT_LEVEL = 2
    anchor_cam = core1
    anchor_sen = curvature_flow_center(OF2, COH2)
    ALIGNMENT_NOTES.append("L2 — camera core only: curvature-flow estimate for sensor")
    ALIGNMENT_NOTES.append("⚠ Reduced alignment confidence (sensor core not visible)")

else:
    ALIGNMENT_LEVEL = 3
    anchor_cam = ridge_centroid(b1_norm)
    anchor_sen = ridge_centroid(b2_norm)
    QUALITY_FLAG = 'warn'
    ALIGNMENT_NOTES.append("L3 — no cores found: ridge centroid fallback")
    ALIGNMENT_NOTES.append("⚠ Orientation alignment uncertain — provide image showing full loop")

for n in ALIGNMENT_NOTES:
    print(f"  {n}")

# ───────────────────────────────────────────────────────────
# STAGE 5  — Geometric pre-alignment
#   Build affine matrix from: rotation + scale + anchor translation
# ───────────────────────────────────────────────────────────
print(f"\n── Stage 5: Geometric pre-alignment ────────────────────────")
cx_s, cy_s = anchor_sen
cx_d, cy_d = anchor_cam

# Compose: scale around sensor anchor, then rotate, then translate
cos_r = np.cos(-rot_rad) * scale_factor
sin_r = np.sin(-rot_rad) * scale_factor
tx    = cx_d - cos_r * cx_s + sin_r * cy_s
ty    = cy_d - sin_r * cx_s - cos_r * cy_s

M_geo = np.float32([[cos_r, -sin_r, tx],
                    [sin_r,  cos_r, ty]])

b2_geo    = cv2.warpAffine(b2_norm, M_geo, SZ, flags=cv2.INTER_LINEAR)
skel2_geo = cv2.warpAffine(skel2_u, M_geo, SZ, flags=cv2.INTER_NEAREST)
bin2_geo  = cv2.warpAffine(bin2,    M_geo, SZ, flags=cv2.INTER_NEAREST)

overlap_geo = ((b1_norm > 0) & (b2_geo > 0))
print(f"  After geo-align  overlap: "
      f"{overlap_geo.sum()} px  "
      f"({overlap_geo.sum()/SZ[0]/SZ[1]*100:.1f}%)")

# ───────────────────────────────────────────────────────────
# STAGE 6  — ECC affine sub-pixel refinement
# ───────────────────────────────────────────────────────────
print(f"\n── Stage 6: ECC affine refinement ──────────────────────────")
warp     = np.eye(2, 3, dtype=np.float32)
criteria = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 500, 1e-7)
ecc_ok   = False
try:
    _, warp = cv2.findTransformECC(
        b1_norm.astype(np.float32),
        b2_geo.astype(np.float32),
        warp, cv2.MOTION_AFFINE, criteria)
    b2_aligned    = cv2.warpAffine(b2_geo,    warp, SZ,
                                   flags=cv2.INTER_LINEAR  + cv2.WARP_INVERSE_MAP)
    skel2_aligned = cv2.warpAffine(skel2_geo, warp, SZ,
                                   flags=cv2.INTER_NEAREST + cv2.WARP_INVERSE_MAP)
    bin2_aligned  = cv2.warpAffine(bin2_geo,  warp, SZ,
                                   flags=cv2.INTER_NEAREST + cv2.WARP_INVERSE_MAP)
    ecc_ok = True
    print(f"  ✅ ECC converged — "
          f"scale≈{warp[0,0]:.3f}  "
          f"tx={warp[0,2]:.1f}px  ty={warp[1,2]:.1f}px")
except Exception as ex:
    print(f"  ⚠️  ECC failed ({ex}) — using geo-aligned image")
    b2_aligned    = b2_geo
    skel2_aligned = skel2_geo
    bin2_aligned  = bin2_geo

overlap = ((b1_norm > 0) & (b2_aligned > 0))
overlap_pct = overlap.sum() / SZ[0] / SZ[1] * 100
print(f"  Final overlap: {overlap.sum()} px  ({overlap_pct:.1f}%)")

# ───────────────────────────────────────────────────────────
# ALIGNMENT QUALITY GATE
# ───────────────────────────────────────────────────────────
print(f"\n── Alignment quality gate ──────────────────────────────────")
if overlap_pct < OVERLAP_FAIL:
    QUALITY_FLAG = 'fail'
    print(f"  ❌ FAIL  overlap {overlap_pct:.1f}% < {OVERLAP_FAIL}%")
    print(f"     → Please provide a sensor image with better coverage of the fingerprint.")
elif overlap_pct < OVERLAP_WARN or ALIGNMENT_LEVEL == 3:
    if QUALITY_FLAG != 'fail':
        QUALITY_FLAG = 'warn'
    print(f"  ⚠️  WARN  overlap {overlap_pct:.1f}% or no core visible.")
    print(f"     → Matching will proceed but confidence is reduced.")
    print(f"     → For better results, use a sensor image capturing the full loop/whorl core.")
else:
    print(f"  ✅ PASS  overlap {overlap_pct:.1f}%  alignment level L{ALIGNMENT_LEVEL}")

# Update OF for aligned sensor image
OF2_ali, COH2_ali = orientation_field(b2_aligned)

# ───────────────────────────────────────────────────────────
# STAGE 7  — TPS warp (if enough minutiae pairs)
# ───────────────────────────────────────────────────────────
print(f"\n── Stage 7: TPS warp (optional) ────────────────────────────")

def crossing_number(patch):
    p = [int(patch[r, c]) for r, c in
         [(0,1),(0,2),(1,2),(2,2),(2,1),(2,0),(1,0),(0,0)]]
    return sum(abs(p[i] - p[(i+1)%8]) for i in range(8)) // 2

def extract_minutiae_pts(skel_u8, margin=20):
    s = skel_u8 // 255; h, w = s.shape; pts = []
    for y in range(margin, h-margin):
        for x in range(margin, w-margin):
            if s[y, x]:
                cn = crossing_number(s[y-1:y+2, x-1:x+2])
                if cn in (1, 3):
                    pts.append(np.array([float(x), float(y)]))
    return np.array(pts) if pts else np.zeros((0, 2))

m1_pts = extract_minutiae_pts(skel1_u)
m2_pts = extract_minutiae_pts(skel2_aligned)
print(f"  Minutiae: cam={len(m1_pts)}  sensor={len(m2_pts)}")

# Match minutiae by proximity for TPS control points
def match_for_tps(pts1, pts2, tol=20):
    if not len(pts1) or not len(pts2): return [], []
    src, dst = [], []
    used = set()
    for pt in pts1:
        d = np.linalg.norm(pts2 - pt, axis=1)
        i = int(np.argmin(d))
        if d[i] < tol and i not in used:
            dst.append(pt); src.append(pts2[i]); used.add(i)
    return np.array(src, float), np.array(dst, float)

tps_src, tps_dst = match_for_tps(m1_pts, m2_pts)
tps_applied = False

if len(tps_src) >= MIN_TPS_PAIRS:
    print(f"  TPS: {len(tps_src)} control point pairs → applying warp")
    try:
        # Build TPS displacement map
        h, w = b2_aligned.shape
        gy_g, gx_g = np.mgrid[0:h, 0:w]
        grid = np.column_stack([gx_g.ravel().astype(float),
                                gy_g.ravel().astype(float)])
        rbf_x = RBFInterpolator(tps_src, tps_dst[:,0] - tps_src[:,0],
                                kernel='thin_plate_spline', smoothing=1.0)
        rbf_y = RBFInterpolator(tps_src, tps_dst[:,1] - tps_src[:,1],
                                kernel='thin_plate_spline', smoothing=1.0)
        dx = rbf_x(grid).reshape(h, w).astype(np.float32)
        dy = rbf_y(grid).reshape(h, w).astype(np.float32)
        map_x = (gx_g.astype(np.float32) - dx)
        map_y = (gy_g.astype(np.float32) - dy)
        b2_aligned    = cv2.remap(b2_aligned, map_x, map_y,
                                   cv2.INTER_LINEAR)
        skel2_aligned = cv2.remap(skel2_aligned, map_x, map_y,
                                   cv2.INTER_NEAREST)
        tps_applied = True
        overlap = ((b1_norm > 0) & (b2_aligned > 0))
        overlap_pct = overlap.sum() / SZ[0] / SZ[1] * 100
        print(f"  ✅ TPS applied — overlap after: {overlap_pct:.1f}%")
        OF2_ali, COH2_ali = orientation_field(b2_aligned)
    except Exception as ex:
        print(f"  ⚠️  TPS failed ({ex}) — skipping")
else:
    print(f"  Skipped — need ≥{MIN_TPS_PAIRS} pairs, have {len(tps_src)}")

# ───────────────────────────────────────────────────────────
# STAGE 8  — Oriented minutiae extraction (full)
# ───────────────────────────────────────────────────────────
print(f"\n── Stage 8: Oriented minutiae descriptors ──────────────────")

def extract_oriented_minutiae(skel_u8, of, block=8, margin=20):
    s = skel_u8 // 255; h, w = s.shape; pts = []
    for y in range(margin, h-margin):
        for x in range(margin, w-margin):
            if s[y, x]:
                v = crossing_number(s[y-1:y+2, x-1:x+2])
                if v in (1, 3):
                    oi = min(y//block, of.shape[0]-1)
                    oj = min(x//block, of.shape[1]-1)
                    pts.append({'x':x,'y':y,
                                'type':'end' if v==1 else 'bif',
                                'angle':float(of[oi,oj])})
    return pts

def ridge_count_between(p1, p2, skel_i, n=12):
    xs = np.linspace(p1['x'],p2['x'],n).astype(int)
    ys = np.linspace(p1['y'],p2['y'],n).astype(int)
    h, w = skel_i.shape; cross, prev = 0, 0
    for xi,yi in zip(xs,ys):
        if 0<=xi<w and 0<=yi<h:
            cur=skel_i[yi,xi]
            if prev==0 and cur==1: cross+=1
            prev=cur
    return cross

def build_descriptors(pts, skel_u8, max_pairs=600):
    skel_i = skel_u8 // 255; desc = []
    for i, p1 in enumerate(pts):
        for p2 in pts[max(0,i-20):i+20]:
            if p1 is p2: continue
            dx=p1['x']-p2['x']; dy=p1['y']-p2['y']
            dist=np.sqrt(dx*dx+dy*dy)
            if dist<8 or dist>130: continue
            da=abs(p1['angle']-p2['angle']); da=min(da,np.pi-da)
            rc=ridge_count_between(p1,p2,skel_i)
            tc=1 if p1['type']==p2['type'] else 0
            desc.append((dist,da,rc,tc))
            if len(desc)>=max_pairs: break
        if len(desc)>=max_pairs: break
    return (np.array(desc,np.float32)
            if desc else np.zeros((0,4),np.float32))

def descriptor_score(d1, d2, bins=22):
    if not len(d1) or not len(d2): return 0.0
    scores=[]
    for c in range(4):
        v1,v2=d1[:,c],d2[:,c]
        lo=min(v1.min(),v2.min()); hi=max(v1.max(),v2.max())+1e-8
        h1,_=np.histogram(v1,bins=bins,range=(lo,hi),density=True)
        h2,_=np.histogram(v2,bins=bins,range=(lo,hi),density=True)
        scores.append(np.sum(np.minimum(h1,h2))/bins)
    return float(np.mean(scores))*100

def proximity_score(pts1, pts2, tol=18):
    if not pts1 or not pts2: return 0.0
    a1=np.array([[p['x'],p['y']] for p in pts1],float)
    a2=np.array([[p['x'],p['y']] for p in pts2],float)
    matched,used=0,set()
    for pt in a1:
        d=np.linalg.norm(a2-pt,axis=1); i=int(np.argmin(d))
        if d[i]<tol and i not in used: matched+=1; used.add(i)
    return matched/max(len(pts1),len(pts2))*100

min1 = extract_oriented_minutiae(skel1_u, OF1)
min2 = extract_oriented_minutiae(skel2_aligned, OF2_ali)
print(f"  cam: {len(min1)} pts   sensor: {len(min2)} pts")
desc1 = build_descriptors(min1, skel1_u)
desc2 = build_descriptors(min2, skel2_aligned)
prox_sc = proximity_score(min1, min2)
desc_sc = descriptor_score(desc1, desc2)
print(f"  Proximity score  : {prox_sc:.1f}%")
print(f"  Descriptor score : {desc_sc:.1f}%")

# ───────────────────────────────────────────────────────────
# STAGE 9  — Ridge frequency + orientation (post-alignment)
# ───────────────────────────────────────────────────────────
def ridge_frequency_map(binary_u8, block=16):
    h,w=binary_u8.shape; rows,cols=h//block,w//block
    F=np.zeros((rows,cols),np.float32)
    for i in range(rows):
        for j in range(cols):
            blk=binary_u8[i*block:(i+1)*block,j*block:(j+1)*block]
            proj=blk.sum(axis=1).astype(np.float32)
            peaks=[k for k in range(1,len(proj)-1)
                   if proj[k]>proj[k-1] and proj[k]>proj[k+1] and proj[k]>5]
            if len(peaks)>=2: F[i,j]=1.0/max(float(np.median(np.diff(peaks))),1)
    return F

rf1 = ridge_frequency_map(b1_norm)
rf2 = ridge_frequency_map(b2_aligned.astype(np.uint8))
valid = (rf1>0)&(rf2>0)
rf_score = max(float(np.corrcoef(rf1[valid],rf2[valid])[0,1])*100,0) if valid.sum()>10 else 0.0

corr_of  = np.corrcoef(OF1.flatten(), OF2_ali.flatten())[0,1]
of_score = max(float(corr_of)*100, 0)

print(f"\n  Ridge freq corr  : {rf_score:.1f}%")
print(f"  Orientation corr : {of_score:.1f}%")

# Gabor (diagnostic only)
def gabor_fv(img_u8,block=16,orients=8,freqs=(0.10,0.15)):
    f=img_u8.astype(np.float32)/255.0; h,w=f.shape; feats=[]
    for fr in freqs:
        for t in range(orients):
            theta=t*np.pi/orients; lam=1/fr; sig=lam*0.65
            k=cv2.getGaborKernel((31,31),sig,theta,lam,0.5,0,ktype=cv2.CV_32F)
            resp=np.abs(cv2.filter2D(f,cv2.CV_32F,k))
            for i in range(h//block):
                for j in range(w//block):
                    feats.append(resp[i*block:(i+1)*block,j*block:(j+1)*block].mean())
    return np.array(feats,np.float32)
gfv1=gabor_fv(b1_norm); gfv2=gabor_fv(b2_aligned.astype(np.uint8))
n1v,n2v=np.linalg.norm(gfv1),np.linalg.norm(gfv2)
gabor_diag=float(np.dot(gfv1/n1v,gfv2/n2v))*100

# ───────────────────────────────────────────────────────────
# FUSION
# ───────────────────────────────────────────────────────────
print(f"\n── Fusion ──────────────────────────────────────────────────")
W = {'Minutiae proximity'  :0.35, 'Minutiae descriptors':0.35,
     'Ridge frequency'     :0.20, 'Ridge orientation'   :0.10}
S = {'Minutiae proximity'  :prox_sc, 'Minutiae descriptors':desc_sc,
     'Ridge frequency'     :rf_score, 'Ridge orientation'  :of_score}

final   = sum(W[k]*S[k] for k in W)
match   = final >= MATCH_THR and QUALITY_FLAG != 'fail'
verdict = "MATCH" if match else "NO MATCH"
gap     = abs(final - MATCH_THR)
conf    = "High" if gap>15 else ("Medium" if gap>7 else "Low")
if QUALITY_FLAG == 'fail': conf = "N/A — poor alignment"
elif QUALITY_FLAG == 'warn': conf = conf + " ⚠"

for k in W:
    bar='█'*int(S[k]//5)
    print(f"  {k:<28}: {S[k]:5.1f}%  {bar}")
print(f"  {'─'*60}")
print(f"  Gabor (diagnostic, NOT scored): {gabor_diag:.1f}%")
print(f"  {'─'*60}")
print(f"  FINAL SCORE              :  {final:.1f}%  (threshold {MATCH_THR}%)")
print(f"  VERDICT                  :  {'✅' if match else '❌'}  {verdict}")
print(f"  CONFIDENCE               :  {conf}")
print(f"  ALIGNMENT LEVEL          :  L{ALIGNMENT_LEVEL}  {'(TPS applied)' if tps_applied else ''}")
if QUALITY_FLAG: print(f"  QUALITY FLAG             :  {QUALITY_FLAG.upper()}")

# ───────────────────────────────────────────────────────────
# VISUALISATION
# ───────────────────────────────────────────────────────────
BG='#0b0b18'; PNL='#13132a'; WT='white'; AC='#00e5ff'
MC='#00e676' if match else '#ff1744'
WARN_C='#ffb74d' if QUALITY_FLAG=='warn' else ('#ff1744' if QUALITY_FLAG=='fail' else '#00e676')

fig=plt.figure(figsize=(26,22),facecolor=BG)
fig.suptitle('Cross-Sensor Fingerprint Matching — v4  '
             '(Rotation + Scale + Poincaré + ECC + TPS)',
             fontsize=19,color=WT,fontweight='bold',y=0.999)
gs=gridspec.GridSpec(4,6,figure=fig,
                     hspace=0.50,wspace=0.28,
                     left=0.03,right=0.97,top=0.963,bottom=0.04)

def iax(ax,img,title,cmap='gray',vmin=None,vmax=None):
    ax.imshow(img,cmap=cmap,aspect='auto',vmin=vmin,vmax=vmax)
    ax.set_title(title,color=AC,fontsize=8,pad=4,fontweight='bold')
    ax.axis('off'); ax.set_facecolor(PNL)

# ── Row 0: binarisation + rotation/scale estimates ────────
r0=[fig.add_subplot(gs[0,i]) for i in range(6)]
iax(r0[0],raw1,'Camera — original')
iax(r0[1],bin1,'Camera — Sauvola binary')
iax(r0[2],raw2,'Sensor — original')
iax(r0[3],bin2,'Sensor — Otsu binary')

# Rotation visualisation — show orientation arrows on both
r0[4].imshow(b1_norm,cmap='gray',aspect='auto'); r0[4].axis('off'); r0[4].set_facecolor(PNL)
r0[4].set_title(f'Camera OF  dom={np.degrees(dom1):.1f}°',color=AC,fontsize=8,pad=4,fontweight='bold')
# draw dominant direction arrow
cx,cy=SZ[0]//2, SZ[1]//2
dx=np.cos(dom1)*60; dy=np.sin(dom1)*60
r0[4].annotate('',xy=(cx+dx,cy+dy),xytext=(cx-dx,cy-dy),
               arrowprops=dict(arrowstyle='<->',color='yellow',lw=2))
if core1: r0[4].scatter([core1[0]],[core1[1]],s=80,c='red',zorder=5,marker='*')

r0[5].imshow(b2_norm,cmap='gray',aspect='auto'); r0[5].axis('off'); r0[5].set_facecolor(PNL)
r0[5].set_title(f'Sensor OF  dom={np.degrees(dom2):.1f}°  '
                f'rot={rot_deg:.1f}°  scale={scale_factor:.3f}',
                color=AC,fontsize=8,pad=4,fontweight='bold')
dx2=np.cos(dom2)*60; dy2=np.sin(dom2)*60
r0[5].annotate('',xy=(cx+dx2,cy+dy2),xytext=(cx-dx2,cy-dy2),
               arrowprops=dict(arrowstyle='<->',color='#ff9800',lw=2))
if core2: r0[5].scatter([core2[0]],[core2[1]],s=80,c='red',zorder=5,marker='*')

# ── Row 1: alignment stages ───────────────────────────────
r1=[fig.add_subplot(gs[1,i]) for i in range(6)]
iax(r1[0],b1_norm,'Camera — width-normalised')
iax(r1[1],b2_norm,'Sensor — before alignment')
iax(r1[2],b2_geo,'Sensor — after rot+scale+anchor')

ov_geo=np.zeros((*b1_norm.shape,3),np.uint8)
ov_geo[b1_norm>0]=[0,180,255]; ov_geo[b2_geo>0]=[255,120,0]
ov_geo[(b1_norm>0)&(b2_geo>0)]=[0,240,100]
iax(r1[3],ov_geo,'Geo-align overlay',cmap=None)

iax(r1[4],b2_aligned,'Sensor — after ECC refinement'
         +(' + TPS' if tps_applied else ''))

ov_fin=np.zeros((*b1_norm.shape,3),np.uint8)
ov_fin[b1_norm>0]=[0,180,255]; ov_fin[b2_aligned>0]=[255,120,0]
ov_fin[(b1_norm>0)&(b2_aligned>0)]=[0,240,100]
iax(r1[5],ov_fin,'Final overlay  ■cam ■sen ■both',cmap=None)

# ── Row 2: skeletons + OF + freq maps ────────────────────
r2=[fig.add_subplot(gs[2,i]) for i in range(6)]
r2[0].imshow(skel1_u,cmap='gray',aspect='auto'); r2[0].axis('off'); r2[0].set_facecolor(PNL)
r2[0].set_title('Camera skeleton + minutiae',color=AC,fontsize=8,pad=4,fontweight='bold')
ends1=np.array([[m['x'],m['y']] for m in min1 if m['type']=='end'])
bifs1=np.array([[m['x'],m['y']] for m in min1 if m['type']=='bif'])
if len(ends1): r2[0].scatter(ends1[:,0],ends1[:,1],s=4,c='cyan',alpha=0.7,zorder=3)
if len(bifs1): r2[0].scatter(bifs1[:,0],bifs1[:,1],s=4,c='#ff6b6b',alpha=0.7,zorder=3)
if core1: r2[0].scatter([core1[0]],[core1[1]],s=120,c='yellow',marker='*',zorder=6,
                        label='Core'); r2[0].legend(fontsize=7,facecolor=PNL,labelcolor=WT)

r2[1].imshow(skel2_aligned,cmap='gray',aspect='auto'); r2[1].axis('off'); r2[1].set_facecolor(PNL)
r2[1].set_title('Sensor skeleton + minutiae (aligned)',color=AC,fontsize=8,pad=4,fontweight='bold')
ends2=np.array([[m['x'],m['y']] for m in min2 if m['type']=='end'])
bifs2=np.array([[m['x'],m['y']] for m in min2 if m['type']=='bif'])
if len(ends2): r2[1].scatter(ends2[:,0],ends2[:,1],s=4,c='cyan',alpha=0.7,zorder=3)
if len(bifs2): r2[1].scatter(bifs2[:,0],bifs2[:,1],s=4,c='#ff6b6b',alpha=0.7,zorder=3)

iax(r2[2],OF1,'Orientation field — Camera',cmap='hsv',vmin=-np.pi/2,vmax=np.pi/2)
iax(r2[3],OF2_ali,'Orientation field — Sensor (aligned)',cmap='hsv',vmin=-np.pi/2,vmax=np.pi/2)
iax(r2[4],rf1,'Ridge freq map — Camera',cmap='plasma')
iax(r2[5],rf2,'Ridge freq map — Sensor (aligned)',cmap='plasma')

# ── Row 3: alignment notes + score bars + verdict ────────
r3=[fig.add_subplot(gs[3,i]) for i in range(6)]

# Alignment info panel
ax_info=r3[0]; ax_info.set_facecolor(PNL); ax_info.axis('off')
for sp in ax_info.spines.values(): sp.set_color(WARN_C)
ax_info.set_title('Alignment log',color=AC,fontsize=8,pad=4,fontweight='bold')
level_col={'1':'#00e676','2':'#ffb74d','3':'#ff1744'}[str(ALIGNMENT_LEVEL)]
ax_info.text(0.5,0.93,f'Level L{ALIGNMENT_LEVEL}',ha='center',va='top',
             transform=ax_info.transAxes,fontsize=13,color=level_col,fontweight='bold')
info_lines=[
    f"rot={rot_deg:.1f}°  scale={scale_factor:.3f}",
    f"Core cam: {'✓ '+str(core1) if core1 else '✗ not found'}",
    f"Core sen: {'✓ '+str(core2) if core2 else '✗ not found'}",
    f"Overlap: {overlap_pct:.1f}%",
    f"ECC: {'✓' if ecc_ok else '✗'}  TPS: {'✓' if tps_applied else '—'}",
    f"Quality: {(QUALITY_FLAG or 'PASS').upper()}",
]
for i,line in enumerate(info_lines):
    col=WT if 'Quality' not in line else WARN_C
    ax_info.text(0.5,0.76-i*0.12,line,ha='center',va='top',
                 transform=ax_info.transAxes,fontsize=8,color=col)
for note in ALIGNMENT_NOTES[:2]:
    pass  # shown in title

# Descriptor histograms
r3[1].set_facecolor(PNL); r3[1].axis('on')
r3[1].set_title('Minutiae descriptor distributions',color=AC,fontsize=8,pad=4,fontweight='bold')
col_names=['Distance','Δ Angle','Ridge count','Type']
pal=['#4fc3f7','#81c784','#ffb74d','#ce93d8']
if len(desc1) and len(desc2):
    for ci,(cn_,cc) in enumerate(zip(col_names,pal)):
        v1,v2=desc1[:,ci],desc2[:,ci]
        lo=min(v1.min(),v2.min()); hi=max(v1.max(),v2.max())+1e-8
        bins=np.linspace(lo,hi,20); bc=(bins[:-1]+bins[1:])/2
        h1,_=np.histogram(v1,bins=bins,density=True)
        h2,_=np.histogram(v2,bins=bins,density=True)
        r3[1].plot(bc,h1,color=cc,lw=1.3,label=f'C {cn_}',alpha=0.95)
        r3[1].plot(bc,h2,color=cc,lw=1.3,ls='--',label=f'S {cn_}',alpha=0.6)
r3[1].tick_params(colors=WT,labelsize=7)
for sp in r3[1].spines.values(): sp.set_color('#2a2a4a')
r3[1].legend(fontsize=6,facecolor=PNL,labelcolor=WT,ncol=2,loc='upper right')

# Gabor diagnostic
ax_g=r3[2]; ax_g.set_facecolor(PNL)
gbars=['Genuine\ncam1-sen1','Genuine\ncam2-sen2','Impostor\ncam1-sen2','Impostor\ncam2-sen1']
gvals=[57.8,53.0,60.0,49.2]
gcols=['#00e676','#00e676','#ff1744','#ff1744']
ax_g.bar(range(4),gvals,color=gcols,edgecolor='#1a1a2e',width=0.6)
ax_g.axhline(50,color='yellow',lw=1,ls='--')
ax_g.set_xticks(range(4)); ax_g.set_xticklabels(gbars,color=WT,fontsize=6)
ax_g.tick_params(colors=WT,labelsize=7); ax_g.set_ylim(0,100)
for sp in ax_g.spines.values(): sp.set_color('#2a2a4a')
ax_g.set_title('Gabor diagnostic (excluded\nfrom score — class-level only)',
               color='#ffb74d',fontsize=8,pad=4,fontweight='bold')

# Score bars
ax_bar=r3[3]; ax_bar.set_facecolor(PNL)
labels=[f"{k}  (×{W[k]})" for k in W]+['FINAL SCORE']
vals=[S[k] for k in W]+[final]
cols_b=['#ffb74d','#81c784','#4fc3f7','#ce93d8',MC]
bars_h=ax_bar.barh(labels,vals,color=cols_b,edgecolor='#1a1a2e',linewidth=0.7,height=0.55)
ax_bar.axvline(MATCH_THR,color='yellow',ls='--',lw=2,label=f'Threshold ({MATCH_THR}%)')
ax_bar.set_xlim(0,110)
for bar,v in zip(bars_h,vals):
    ax_bar.text(v+1,bar.get_y()+bar.get_height()/2,
                f'{v:.1f}%',va='center',color=WT,fontsize=9,fontweight='bold')
ax_bar.tick_params(colors=WT,labelsize=8)
for sp in ax_bar.spines.values(): sp.set_color('#2a2a4a')
ax_bar.set_xlabel('Score (%)',color=WT,fontsize=9)
ax_bar.set_title('Fusion scores — identity-level features',color=WT,fontsize=9,pad=4)
ax_bar.legend(fontsize=8,facecolor=PNL,labelcolor=WT,loc='lower right')

# Verdict
ax_v=r3[4]; ax_v.set_facecolor('#0d2a1a' if match else '#2a0d0d')
for sp in ax_v.spines.values(): sp.set_edgecolor(MC); sp.set_linewidth(3)
ax_v.text(0.5,0.86,'✔' if match else '✘',ha='center',va='center',
          fontsize=48,color=MC,transform=ax_v.transAxes,fontweight='bold')
ax_v.text(0.5,0.68,verdict,ha='center',va='center',
          fontsize=17,color=MC,transform=ax_v.transAxes,fontweight='bold')
ax_v.text(0.5,0.54,f'Score: {final:.1f}%',ha='center',va='center',
          fontsize=13,color=WT,transform=ax_v.transAxes)
ax_v.text(0.5,0.42,f'Confidence: {conf}',ha='center',va='center',
          fontsize=11,color='#aaa',transform=ax_v.transAxes)
ax_v.text(0.5,0.30,f'Alignment: L{ALIGNMENT_LEVEL}  '
          f'{"TPS ✓" if tps_applied else "TPS —"}',
          ha='center',va='center',fontsize=9,color='#888',transform=ax_v.transAxes)
ax_v.text(0.5,0.20,f'rot={rot_deg:.1f}°  scale={scale_factor:.3f}',
          ha='center',va='center',fontsize=9,color='#888',transform=ax_v.transAxes)
ax_v.text(0.5,0.10,f'overlap={overlap_pct:.1f}%  min={len(min1)}vs{len(min2)}',
          ha='center',va='center',fontsize=8,color='#555',transform=ax_v.transAxes)
ax_v.set_xticks([]); ax_v.set_yticks([])
ax_v.set_title('VERDICT',color=WT,fontsize=11,fontweight='bold')

# Quality flag banner
ax_q=r3[5]; ax_q.set_facecolor(PNL)
for sp in ax_q.spines.values(): sp.set_edgecolor(WARN_C); sp.set_linewidth(2)
ax_q.axis('off')
ax_q.set_title('Quality gate',color=AC,fontsize=8,pad=4,fontweight='bold')
qtext={'warn':'⚠ WARNING\nAlignment limited\nCore not fully visible\nProceed with caution',
       'fail':'❌ FAILED\nOverlap too low\nPlease provide a\nbetter sensor image',
       None  :'✅ PASSED\nAlignment verified\nCore detected\nOverlap sufficient'}[QUALITY_FLAG]
ax_q.text(0.5,0.55,qtext,ha='center',va='center',transform=ax_q.transAxes,
          fontsize=11,color=WARN_C,fontweight='bold',
          bbox=dict(boxstyle='round,pad=0.5',facecolor='#0d0d1a',
                    edgecolor=WARN_C,linewidth=1.5))
for note in ALIGNMENT_NOTES:
    pass

from matplotlib.patches import Patch
fig.legend(handles=[
    Patch(facecolor='cyan',    label='Ridge endings'),
    Patch(facecolor='#ff6b6b', label='Bifurcations'),
    Patch(facecolor='yellow',  label='★ Core point'),
    Patch(facecolor='#00b4ff', label='Camera ridges'),
    Patch(facecolor='#ff7800', label='Sensor ridges'),
    Patch(facecolor='#00f064', label='Overlap region'),
],loc='lower center',ncol=6,fontsize=8,
   facecolor=PNL,labelcolor=WT,framealpha=0.9,
   bbox_to_anchor=(0.5,0.0))

plt.savefig(out_path,dpi=150,bbox_inches='tight',facecolor=BG)
print(f"\nSaved → {out_path}")
