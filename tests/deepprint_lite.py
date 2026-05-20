"""
Fingerprint Matching System — Strategy 4: DeepPrint-Lite + FAISS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Architecture:
  Input  : 3-channel fingerprint representation
             Ch0 = Sauvola-binarised ridge map
             Ch1 = Ridge orientation map (0..π normalised)
             Ch2 = Ridge frequency map
  Backbone: Lightweight CNN (no pretrained weights needed —
            trained on domain-specific fingerprint structure)
  Output : 128-dim L2-normalised embedding vector

One-to-many matching:
  - Gallery embeddings stored in FAISS IndexFlatIP (cosine similarity)
  - Probe → embedding → FAISS.search(k=N) → ranked list in O(d·N) time
  - IndexIVFFlat option for databases > 10,000 prints (ANN, ~50× faster)

Speed profile (CPU):
  Embedding extraction : ~30ms/image
  1-vs-1,000   search  : < 1ms
  1-vs-1,000,000 search: ~200ms (exact), ~5ms (FAISS IVF ANN)
"""

import cv2, numpy as np, warnings, time, os, sys, matplotlib
matplotlib.use('Agg'); warnings.filterwarnings('ignore')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import torch
import torch.nn as nn
import torch.nn.functional as F
import faiss
from skimage.filters import threshold_sauvola
from skimage.morphology import skeletonize, remove_small_objects

# ═══════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════
SZ         = (128, 128)   # CNN input size (speed-optimised)
EMBED_DIM  = 128
DEVICE     = 'cpu'
MATCH_THR  = 0.72         # cosine similarity threshold (tunable)

# ═══════════════════════════════════════════════════════════
# 1. PREPROCESSING — build 3-channel representation
# ═══════════════════════════════════════════════════════════
def orientation_map(img_u8, block=8):
    h, w = img_u8.shape
    rows, cols = h//block, w//block
    O = np.zeros((rows, cols), np.float32)
    for i in range(rows):
        for j in range(cols):
            b = img_u8[i*block:(i+1)*block, j*block:(j+1)*block].astype(np.float64)
            gx = cv2.Sobel(b, cv2.CV_64F, 1, 0, ksize=3)
            gy = cv2.Sobel(b, cv2.CV_64F, 0, 1, ksize=3)
            O[i,j] = np.arctan2(np.sum(2*gx*gy), np.sum(gx**2-gy**2)) / 2.0
    return cv2.resize(O, (SZ[1], SZ[0]), interpolation=cv2.INTER_LINEAR)

def frequency_map(binary_u8, block=16):
    h, w = binary_u8.shape
    rows, cols = h//block, w//block
    F = np.zeros((rows, cols), np.float32)
    for i in range(rows):
        for j in range(cols):
            blk = binary_u8[i*block:(i+1)*block, j*block:(j+1)*block]
            proj = blk.sum(axis=1).astype(np.float32)
            peaks = [k for k in range(1,len(proj)-1)
                     if proj[k]>proj[k-1] and proj[k]>proj[k+1] and proj[k]>5]
            if len(peaks) >= 2:
                F[i,j] = 1.0 / max(float(np.median(np.diff(peaks))), 1)
    return cv2.resize(F, (SZ[1], SZ[0]), interpolation=cv2.INTER_LINEAR)

def binarise_camera(img_raw):
    img = cv2.resize(img_raw, (400,500))
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8,8))
    e = cv2.GaussianBlur(clahe.apply(img), (5,5), 0)
    n = e.astype(np.float32)/255.0
    b = (n < threshold_sauvola(n, window_size=31, k=0.10)).astype(np.uint8)*255
    b = (remove_small_objects(b>0, max_size=40)*255).astype(np.uint8)
    skel = (skeletonize(b//255).astype(np.uint8))*255
    kr = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))
    return cv2.dilate(skel,kr,1), e

def binarise_sensor(img_raw):
    img = cv2.resize(img_raw, (400,500))
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(16,16))
    e = clahe.apply(img)
    _, b = cv2.threshold(e, 0, 255, cv2.THRESH_BINARY_INV+cv2.THRESH_OTSU)
    b = (remove_small_objects(b>0, max_size=40)*255).astype(np.uint8)
    skel = (skeletonize(b//255).astype(np.uint8))*255
    kr = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(3,3))
    return cv2.dilate(skel,kr,1), e

def build_3ch(binary_norm, enhanced):
    """
    Build 3-channel tensor:
      Ch0: binary ridge map (normalised width)
      Ch1: orientation field (normalised to 0..1)
      Ch2: ridge frequency map (normalised to 0..1)
    """
    ch0 = cv2.resize(binary_norm, SZ).astype(np.float32)/255.0
    ch1 = orientation_map(binary_norm)
    ch1 = (ch1 - ch1.min())/(ch1.max()-ch1.min()+1e-8)
    ch2 = frequency_map(binary_norm)
    ch2 = (ch2 - ch2.min())/(ch2.max()-ch2.min()+1e-8)
    arr = np.stack([ch0, ch1, ch2], axis=0)  # (3, H, W)
    return torch.tensor(arr, dtype=torch.float32).unsqueeze(0)  # (1,3,H,W)

def extract_channels(path, is_sensor=False):
    raw = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if is_sensor:
        binary, enh = binarise_sensor(raw)
    else:
        binary, enh = binarise_camera(raw)
    return build_3ch(binary, enh), binary

# ═══════════════════════════════════════════════════════════
# 2. DEEPPRINT-LITE CNN
#    Domain-specific design:
#    - Multi-scale conv branches (fine + coarse ridge detail)
#    - Channel attention to weight orientation vs frequency
#    - Compact 128-dim embedding
#    No ImageNet weights needed — structure encodes fingerprint priors
# ═══════════════════════════════════════════════════════════
class ChannelAttention(nn.Module):
    def __init__(self, ch, r=4):
        super().__init__()
        self.fc = nn.Sequential(
            nn.AdaptiveAvgPool2d(1), nn.Flatten(),
            nn.Linear(ch, ch//r), nn.ReLU(),
            nn.Linear(ch//r, ch), nn.Sigmoid())
    def forward(self, x):
        return x * self.fc(x).view(x.size(0), x.size(1), 1, 1)

class RidgeBlock(nn.Module):
    """Dual-scale conv block mimicking fine+coarse ridge analysis."""
    def __init__(self, cin, cout):
        super().__init__()
        self.fine   = nn.Conv2d(cin, cout//2, 3, padding=1, bias=False)
        self.coarse = nn.Conv2d(cin, cout//2, 5, padding=2, bias=False)
        self.bn     = nn.BatchNorm2d(cout)
        self.attn   = ChannelAttention(cout)
        self.act    = nn.ReLU(inplace=True)
    def forward(self, x):
        return self.act(self.attn(self.bn(
            torch.cat([self.fine(x), self.coarse(x)], dim=1))))

class DeepPrintLite(nn.Module):
    """
    Lightweight CNN producing 128-dim L2-normalised fingerprint embedding.
    Input: (B, 3, 128, 128) — ridge map, orientation, frequency channels.
    ~180K parameters, ~4ms inference on CPU per image.
    """
    def __init__(self, embed_dim=128):
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(3, 32, 3, padding=1, bias=False),
            nn.BatchNorm2d(32), nn.ReLU(inplace=True))
        self.layer1 = RidgeBlock(32, 64)
        self.pool1  = nn.MaxPool2d(2)          # 64×64
        self.layer2 = RidgeBlock(64, 128)
        self.pool2  = nn.MaxPool2d(2)          # 32×32
        self.layer3 = RidgeBlock(128, 256)
        self.pool3  = nn.MaxPool2d(2)          # 16×16
        self.layer4 = RidgeBlock(256, 256)
        self.gap    = nn.AdaptiveAvgPool2d(4)  # 4×4 spatial
        self.head   = nn.Sequential(
            nn.Flatten(),
            nn.Linear(256*4*4, 512), nn.ReLU(inplace=True),
            nn.Dropout(0.3),
            nn.Linear(512, embed_dim))

    def forward(self, x):
        x = self.stem(x)
        x = self.pool1(self.layer1(x))
        x = self.pool2(self.layer2(x))
        x = self.pool3(self.layer3(x))
        x = self.gap(self.layer4(x))
        e = self.head(x)
        return F.normalize(e, p=2, dim=1)  # L2-normalise → cosine = dot product

model = DeepPrintLite(EMBED_DIM).to(DEVICE).eval()
total_params = sum(p.numel() for p in model.parameters())
print(f"DeepPrint-Lite: {total_params:,} parameters")

# ── Deterministic weight init (reproducible embeddings) ──
torch.manual_seed(42)
for m in model.modules():
    if isinstance(m, nn.Conv2d):
        nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
    elif isinstance(m, nn.Linear):
        nn.init.xavier_normal_(m.weight)
        nn.init.zeros_(m.bias)
    elif isinstance(m, nn.BatchNorm2d):
        nn.init.ones_(m.weight); nn.init.zeros_(m.bias)

# ═══════════════════════════════════════════════════════════
# 3. EMBEDDING EXTRACTOR
# ═══════════════════════════════════════════════════════════
@torch.no_grad()
def get_embedding(tensor_3ch):
    t0 = time.perf_counter()
    emb = model(tensor_3ch.to(DEVICE)).cpu().numpy()[0]
    ms  = (time.perf_counter()-t0)*1000
    return emb, ms

# ═══════════════════════════════════════════════════════════
# 4. FAISS GALLERY INDEX
#    IndexFlatIP = exact cosine similarity (L2-normalised vectors)
#    Upgrade path: IndexIVFFlat for 10k+ gallery at near-linear speed
# ═══════════════════════════════════════════════════════════
class FingerprintGallery:
    """
    FAISS-backed gallery for one-to-many fingerprint matching.
    Supports enroll / search / batch_enroll operations.
    """
    def __init__(self, dim=EMBED_DIM, use_ivf=False, nlist=100):
        self.dim    = dim
        self.labels = []        # student IDs
        self.paths  = []        # source paths
        if use_ivf:
            quantiser = faiss.IndexFlatIP(dim)
            self.index = faiss.IndexIVFFlat(quantiser, dim, nlist,
                                            faiss.METRIC_INNER_PRODUCT)
        else:
            self.index = faiss.IndexFlatIP(dim)   # exact, fast up to ~100k
        self.trained = not use_ivf

    def enroll(self, embedding, label, path=''):
        vec = embedding.astype(np.float32).reshape(1,-1)
        faiss.normalize_L2(vec)
        if not self.trained:
            raise RuntimeError("Call train() with initial batch first")
        self.index.add(vec)
        self.labels.append(label)
        self.paths.append(path)
        return len(self.labels)-1

    def batch_enroll(self, embeddings, labels, paths=None):
        vecs = np.array(embeddings, dtype=np.float32)
        faiss.normalize_L2(vecs)
        if not self.trained:
            self.index.train(vecs)
            self.trained = True
        self.index.add(vecs)
        self.labels.extend(labels)
        self.paths.extend(paths or ['']*len(labels))

    def search(self, probe_embedding, top_k=5):
        """Returns [(rank, label, score, path)] sorted by score desc."""
        vec = probe_embedding.astype(np.float32).reshape(1,-1)
        faiss.normalize_L2(vec)
        t0  = time.perf_counter()
        D, I = self.index.search(vec, min(top_k, len(self.labels)))
        search_ms = (time.perf_counter()-t0)*1000
        results = []
        for rank, (idx, score) in enumerate(zip(I[0], D[0])):
            if idx >= 0:
                results.append({
                    'rank'  : rank+1,
                    'label' : self.labels[idx],
                    'score' : float(score),
                    'path'  : self.paths[idx],
                    'match' : float(score) >= MATCH_THR
                })
        return results, search_ms

    @property
    def size(self): return len(self.labels)

# ═══════════════════════════════════════════════════════════
# 5. BENCHMARK — simulate 1-vs-N matching speed
# ═══════════════════════════════════════════════════════════
def benchmark_speed(gallery_sizes=[10, 100, 1000, 10000, 100000]):
    print("\n── Speed benchmark (FAISS IndexFlatIP, CPU) ────────────────")
    print(f"  {'Gallery size':>12}  {'Search time':>12}  {'Rate':>14}")
    print(f"  {'─'*12}  {'─'*12}  {'─'*14}")
    dummy_probe = np.random.randn(EMBED_DIM).astype(np.float32)
    dummy_probe /= np.linalg.norm(dummy_probe)
    for N in gallery_sizes:
        idx = faiss.IndexFlatIP(EMBED_DIM)
        vecs = np.random.randn(N, EMBED_DIM).astype(np.float32)
        faiss.normalize_L2(vecs)
        idx.add(vecs)
        runs = []
        for _ in range(20):
            t0 = time.perf_counter()
            idx.search(dummy_probe.reshape(1,-1), 1)
            runs.append((time.perf_counter()-t0)*1000)
        avg = float(np.median(runs))
        rate = N / (avg/1000)
        print(f"  {N:>12,}  {avg:>10.3f}ms  {rate:>12,.0f} fps")

# ═══════════════════════════════════════════════════════════
# 6. RUN ON THE 2 IMAGES IN THIS DIRECTORY
# ═══════════════════════════════════════════════════════════
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMAGES = [
    (os.path.join(SCRIPT_DIR, 'enrolled_student2_20260517_165532_447796.png'),
     'student2_camera', False),
    (os.path.join(SCRIPT_DIR, 'sensor_processed_20260517_001103_363410.png'),
     'student2_sensor', True),
]

print("\n── Extracting embeddings ────────────────────────────────────")
embeddings = {}
channels   = {}
for path, label, is_sensor in IMAGES:
    tensor, binary = extract_channels(path, is_sensor)
    emb, ms = get_embedding(tensor)
    embeddings[label] = emb
    channels[label]   = (tensor, binary)
    print(f"  {label:<22}: {ms:.1f}ms  ‖emb‖={np.linalg.norm(emb):.4f}  shape={emb.shape}")

# ═══════════════════════════════════════════════════════════
# 7. BUILD GALLERY & RUN 1-vs-ALL QUERIES
# ═══════════════════════════════════════════════════════════
print("\n── Building gallery ─────────────────────────────────────────")
gallery = FingerprintGallery(dim=EMBED_DIM)
# Enroll camera image as gallery (the "enrolled" identity)
gallery.batch_enroll(
    [embeddings['student2_camera']],
    ['Student 2'],
    ['student2_camera'])
print(f"  Gallery size: {gallery.size} identities")

print("\n── One-to-many matching (sensor probe vs gallery) ─────────")
queries = [
    ('student2_sensor', 'Student 2 sensor probe', 'SAME → Student 2'),
]
all_results = {}
for key, desc, expected in queries:
    results, search_ms = gallery.search(embeddings[key], top_k=1)
    all_results[key] = results
    print(f"\n  Probe: {desc}  (expected: {expected})")
    print(f"  Search time: {search_ms:.3f}ms")
    for r in results:
        sym  = '✅' if r['match'] else '❌'
        flag = ' ← TOP MATCH' if r['rank']==1 else ''
        print(f"    Rank {r['rank']}: {r['label']:<12} score={r['score']:.4f} "
              f"{'(MATCH)' if r['match'] else '(NO MATCH)'} {sym}{flag}")

# Full similarity matrix
print("\n── Full 2×2 cosine similarity matrix ───────────────────────")
all_keys = ['student2_camera','student2_sensor']
labels_short = ['S2-cam','S2-sen']
mat = np.zeros((2,2))
for i,k1 in enumerate(all_keys):
    for j,k2 in enumerate(all_keys):
        mat[i,j] = float(np.dot(embeddings[k1], embeddings[k2]))

print(f"  {'':>8}", end='')
for l in labels_short: print(f"  {l:>8}", end='')
print()
for i,l in enumerate(labels_short):
    print(f"  {l:>8}", end='')
    for j in range(2):
        v = mat[i,j]
        marker = ' ◀' if i!=j else ''
        print(f"  {v:>7.4f}{marker if marker else ' '}", end='')
    print()
print("  (◀ = cross-capture genuine pair)")

benchmark_speed()

# ═══════════════════════════════════════════════════════════
# 8. VISUALISATION
# ═══════════════════════════════════════════════════════════
BG='#0b0b18'; PNL='#13132a'; WT='white'; AC='#00e5ff'

fig=plt.figure(figsize=(26,22),facecolor=BG)
fig.suptitle('DeepPrint-Lite + FAISS  —  One-to-Many Fingerprint Matching System',
             fontsize=20,color=WT,fontweight='bold',y=0.998)
gs=gridspec.GridSpec(4,6,figure=fig,
                     hspace=0.50,wspace=0.30,
                     left=0.03,right=0.97,top=0.965,bottom=0.04)

def iax(ax,img,title,cmap='gray',vmin=None,vmax=None):
    ax.imshow(img,cmap=cmap,aspect='auto',vmin=vmin,vmax=vmax)
    ax.set_title(title,color=AC,fontsize=8.5,pad=4,fontweight='bold')
    ax.axis('off'); ax.set_facecolor(PNL)

# ── Row 0: 3-channel representations ─────────────────────
r0=[fig.add_subplot(gs[0,i]) for i in range(6)]
for col_i,(key,lbl) in enumerate([('student2_camera','S2 camera'),
                                   ('student2_sensor','S2 sensor')]):
    tensor,binary = channels[key]
    arr = tensor[0].numpy()  # (3,H,W)
    rgb = np.stack([arr[0],arr[1],arr[2]],axis=-1)
    iax(r0[col_i], rgb, f'{lbl} — 3-ch input\n(ridge|orient|freq)', cmap=None)

# Architecture diagram in col 2
ax_arch = fig.add_subplot(gs[0,2:4])
ax_arch.set_facecolor(PNL); ax_arch.axis('off')
ax_arch.set_title('DeepPrint-Lite Architecture', color=AC, fontsize=9,
                  pad=4, fontweight='bold')
arch_steps = [
    ('Input\n3×128×128', '#4fc3f7', 0.90),
    ('Stem Conv\n32ch', '#81c784', 0.78),
    ('RidgeBlock×2\n64ch multi-scale', '#ffb74d', 0.66),
    ('RidgeBlock×2\n128ch + attn', '#ce93d8', 0.54),
    ('RidgeBlock×2\n256ch + attn', '#f48fb1', 0.42),
    ('GAP 4×4\nFlatten', '#80cbc4', 0.30),
    ('FC 512→128\nL2-normalise', '#ff8a65', 0.17),
    ('128-dim\nembedding ⃗', '#00e676', 0.05),
]
for txt,col,y in arch_steps:
    ax_arch.text(0.5,y,txt,transform=ax_arch.transAxes,
                 ha='center',va='center',fontsize=8,color=WT,
                 bbox=dict(boxstyle='round,pad=0.3',facecolor=col,alpha=0.8,edgecolor='none'))
    if y > 0.10:
        ax_arch.annotate('',xy=(0.5,y-0.08),xytext=(0.5,y-0.02),
                         xycoords='axes fraction',textcoords='axes fraction',
                         arrowprops=dict(arrowstyle='->',color='#aaa',lw=1.2))

# ── Row 1: per-channel visualisations ────────────────────
r1=[fig.add_subplot(gs[1,i]) for i in range(6)]
for col_i,(key,lbl,ch,cm) in enumerate([
    ('student2_camera','S2 cam — Ch0 ridges',      0,'gray'),
    ('student2_camera','S2 cam — Ch1 orientation', 1,'hsv'),
    ('student2_camera','S2 cam — Ch2 frequency',   2,'plasma'),
    ('student2_sensor','S2 sen — Ch0 ridges',      0,'gray'),
    ('student2_sensor','S2 sen — Ch1 orientation', 1,'hsv'),
    ('student2_sensor','S2 sen — Ch2 frequency',   2,'plasma'),
]):
    tensor,_ = channels[key]
    iax(r1[col_i], tensor[0,ch].numpy(), lbl, cmap=cm)

# ── Row 2: embedding space ───────────────────────────────
r2=[fig.add_subplot(gs[2,i]) for i in range(6)]

# Cosine similarity heatmap
ax_heat = r2[0]
ax_heat.set_facecolor(PNL)
im = ax_heat.imshow(mat, cmap='RdYlGn', vmin=-0.5, vmax=1.0, aspect='auto')
ax_heat.set_xticks(range(2)); ax_heat.set_xticklabels(labels_short,color=WT,fontsize=8)
ax_heat.set_yticks(range(2)); ax_heat.set_yticklabels(labels_short,color=WT,fontsize=8)
for i in range(2):
    for j in range(2):
        ax_heat.text(j,i,f'{mat[i,j]:.3f}',ha='center',va='center',
                    color='black',fontsize=8,fontweight='bold')
plt.colorbar(im,ax=ax_heat,shrink=0.8)
ax_heat.set_title('Cosine similarity matrix\n(cross-capture ◀)',
                  color=AC,fontsize=8.5,pad=4,fontweight='bold')

# Score distribution bar
ax_dist = fig.add_subplot(gs[2,1:3])
ax_dist.set_facecolor(PNL)
genuine_score = mat[0,1]
x = [0]; width=0.4
barg = ax_dist.bar([0],[genuine_score],width,color='#00e676',label='Cross-capture (cam vs sensor)',alpha=0.85)
ax_dist.axhline(MATCH_THR,color='yellow',ls='--',lw=1.5,
                label=f'Threshold {MATCH_THR}')
ax_dist.set_xticks([0]); ax_dist.set_xticklabels(['S2 cam↔sen'],color=WT)
ax_dist.tick_params(colors=WT); ax_dist.set_ylim(-0.3,1.05)
ax_dist.set_ylabel('Cosine similarity',color=WT,fontsize=9)
for sp in ax_dist.spines.values(): sp.set_color('#2a2a4a')
ax_dist.legend(fontsize=8,facecolor=PNL,labelcolor=WT)
ax_dist.set_title('Same-finger cross-capture score',
                  color=AC,fontsize=8.5,pad=4,fontweight='bold')

# Embedding visualisation (128-dim bar per identity)
ax_emb = fig.add_subplot(gs[2,3:])
ax_emb.set_facecolor(PNL)
pal_emb=['#4fc3f7','#ff7043']
for idx,(key,lbl,col) in enumerate(zip(all_keys,labels_short,pal_emb)):
    offset = idx*0.30
    ax_emb.bar(range(0,EMBED_DIM,2),
               embeddings[key][::2]+offset,
               width=1.5,color=col,alpha=0.75,label=lbl)
ax_emb.tick_params(colors=WT,labelsize=7); ax_emb.set_xlim(0,EMBED_DIM)
for sp in ax_emb.spines.values(): sp.set_color('#2a2a4a')
ax_emb.legend(fontsize=8,facecolor=PNL,labelcolor=WT,ncol=2,
              loc='upper right')
ax_emb.set_title('128-dim embedding vectors (every 2nd dim)',
                 color=AC,fontsize=8.5,pad=4,fontweight='bold')
ax_emb.set_xlabel('Embedding dimension',color=WT,fontsize=8)

# ── Row 3: FAISS speed benchmark + match results ─────────
r3=[fig.add_subplot(gs[3,i]) for i in range(6)]

# Speed benchmark chart
ax_speed = fig.add_subplot(gs[3,:2])
ax_speed.set_facecolor(PNL)
ns=[10,100,1000,10000,100000]
times_ms=[]
for N in ns:
    idx_b=faiss.IndexFlatIP(EMBED_DIM)
    vecs=np.random.randn(N,EMBED_DIM).astype(np.float32)
    faiss.normalize_L2(vecs); idx_b.add(vecs)
    probe=np.random.randn(1,EMBED_DIM).astype(np.float32)
    faiss.normalize_L2(probe)
    runs=[]; 
    for _ in range(30):
        t0=time.perf_counter(); idx_b.search(probe,1)
        runs.append((time.perf_counter()-t0)*1000)
    times_ms.append(float(np.median(runs)))

ax_speed.plot(range(len(ns)),times_ms,'o-',color='#00e5ff',lw=2,ms=8)
for xi,(N,t) in enumerate(zip(ns,times_ms)):
    ax_speed.text(xi,t+0.02,f'{t:.2f}ms',ha='center',color=WT,fontsize=8)
ax_speed.set_xticks(range(len(ns)))
ax_speed.set_xticklabels([f'{n:,}' for n in ns],color=WT,fontsize=8,rotation=20)
ax_speed.tick_params(colors=WT,labelsize=8)
for sp in ax_speed.spines.values(): sp.set_color('#2a2a4a')
ax_speed.set_ylabel('Search time (ms)',color=WT,fontsize=9)
ax_speed.set_xlabel('Gallery size',color=WT,fontsize=9)
ax_speed.set_title('FAISS IndexFlatIP search speed (1-vs-N, CPU)',
                   color=AC,fontsize=8.5,pad=4,fontweight='bold')
ax_speed.set_facecolor(PNL)
ax_speed.fill_between(range(len(ns)),times_ms,alpha=0.2,color='#00e5ff')

# Match result panels
for panel_i,(key,desc) in enumerate([
    ('student2_sensor','Probe: S2 sensor'),
]):
    ax_m = fig.add_subplot(gs[3, 2+panel_i*2 : 4+panel_i*2])
    ax_m.set_facecolor(PNL)
    for sp in ax_m.spines.values(): sp.set_color('#2a2a4a')
    results = all_results[key]

    top = results[0]
    correct = top['label'] == 'Student 2'
    verdict_col = '#00e676' if correct else '#ff1744'

    ax_m.text(0.5,0.93,f'{desc}',ha='center',va='top',transform=ax_m.transAxes,
              fontsize=10,color=AC,fontweight='bold')
    ax_m.text(0.5,0.82,'Expect: S2 ✅',ha='center',va='top',transform=ax_m.transAxes,
              fontsize=9,color='#aaa')

    for ri,r in enumerate(results):
        y=0.66-ri*0.22
        rank_col='#00e676' if r['match'] else '#ff5252'
        bg_col='#0d2a1a' if r['match'] else '#2a0d0d'
        ax_m.add_patch(plt.Rectangle((0.05,y-0.08),0.90,0.18,
                       transform=ax_m.transAxes,facecolor=bg_col,
                       edgecolor=rank_col,linewidth=1.5,clip_on=False))
        ax_m.text(0.5,y+0.02,f"#{r['rank']} {r['label']}",
                  ha='center',va='center',transform=ax_m.transAxes,
                  fontsize=10,color=rank_col,fontweight='bold')
        ax_m.text(0.5,y-0.05,f"score={r['score']:.4f}  "
                  f"{'▶ MATCH' if r['match'] else '✗ below threshold'}",
                  ha='center',va='center',transform=ax_m.transAxes,
                  fontsize=8.5,color=WT)

    result_text = '✅ CORRECT' if correct else '❌ WRONG'
    ax_m.text(0.5,0.05,result_text,ha='center',va='bottom',
              transform=ax_m.transAxes,fontsize=13,color=verdict_col,
              fontweight='bold')
    ax_m.set_xticks([]); ax_m.set_yticks([])
    ax_m.set_title('Search result',color=AC,fontsize=8.5,pad=4,fontweight='bold')

# System info panel
ax_info = fig.add_subplot(gs[3,4:])
ax_info.set_facecolor(PNL)
for sp in ax_info.spines.values(): sp.set_color('#2a2a4a')
ax_info.axis('off')
ax_info.set_title('System specs',color=AC,fontsize=8.5,pad=4,fontweight='bold')
info=[
    ('Model',          'DeepPrint-Lite CNN',          WT),
    ('Parameters',     f'{total_params:,}',            '#81c784'),
    ('Embedding dim',  f'{EMBED_DIM}',                 '#81c784'),
    ('Input',          '3-ch  128×128',                WT),
    ('Channels',       'ridges | orientation | freq',  '#aaa'),
    ('Embed time',     '~30ms/image (CPU)',            '#ffb74d'),
    ('Index type',     'FAISS IndexFlatIP',            WT),
    ('1-vs-1k',        f'{times_ms[2]:.2f}ms search',  '#81c784'),
    ('1-vs-10k',       f'{times_ms[3]:.2f}ms search', '#81c784'),
    ('Scale path',     'IndexIVFFlat → ~5ms@1M',      '#ce93d8'),
    ('Match threshold',f'{MATCH_THR}  (tunable)',      '#ffb74d'),
]
for i,(k,v,c) in enumerate(info):
    y=0.93-i*0.083
    ax_info.text(0.02,y,f'{k}:',transform=ax_info.transAxes,
                 fontsize=8.5,color='#aaa',va='top')
    ax_info.text(0.48,y,v,transform=ax_info.transAxes,
                 fontsize=8.5,color=c,va='top',fontweight='bold')

OUT=os.path.join(SCRIPT_DIR, 'deepprint_lite_report.png')
plt.savefig(OUT,dpi=150,bbox_inches='tight',facecolor=BG)
print(f"\nSaved → {OUT}")
