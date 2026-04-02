# Biometric Fingerprint Processing & Matching System
## Complete Working Mechanism Documentation

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [System Architecture](#2-system-architecture)
3. [Hardware Layer — ESP32 + AS608/R503 Sensor](#3-hardware-layer)
4. [Backend — Django REST API](#4-backend)
5. [Database — PostgreSQL](#5-database)
6. [Image Preprocessing Pipeline](#6-image-preprocessing-pipeline)
7. [Biometric Template Engine](#7-biometric-template-engine)
8. [Fingerprint Matching Engine](#8-fingerprint-matching-engine)
9. [Security & Encryption](#9-security--encryption)
10. [API Endpoints & Request/Response Flow](#10-api-endpoints)
11. [Frontend](#11-frontend)
12. [End-to-End Workflows](#12-end-to-end-workflows)
13. [Technology Stack Summary](#13-technology-stack-summary)

---

## 1. System Overview

This is a **biometric fingerprint identification system** designed for student enrollment and verification. It accepts fingerprint input from two sources — a smartphone camera and a dedicated hardware sensor (ESP32 + AS608/R503/R307) — processes the images through a multi-stage pipeline, extracts unique biometric templates, encrypts them, stores them in a PostgreSQL database, and performs real-time matching against enrolled fingerprints.

### Core Capabilities

- **Dual-input enrollment**: Camera photo upload or hardware sensor capture
- **Multi-stage image preprocessing**: Validation, region detection, normalization, ridge enhancement, noise reduction, orientation correction, quality assessment
- **Minutiae-based template extraction**: Skeletonization + neighborhood analysis to detect ridge endings and bifurcations
- **AES-256-CBC encryption**: Every biometric template is encrypted at rest with a random IV
- **Multi-algorithm matching**: SIFT, ORB, and FLANN matchers combined with weighted scoring
- **Student management**: Full CRUD for student records with medical form PDF uploads

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INPUT SOURCES                                │
│                                                                     │
│   ┌──────────────────┐          ┌──────────────────────────┐       │
│   │  Smartphone       │          │  ESP32 + AS608/R503      │       │
│   │  Camera Photo     │          │  Hardware Sensor         │       │
│   │  (JPEG/PNG)       │          │  (Raw binary image)      │       │
│   └────────┬─────────┘          └───────────┬──────────────┘       │
│            │                                │                       │
│            ▼                                ▼                       │
│   POST /api/fingerprint/upload/   POST /api/fingerprint/           │
│                                   sensor-capture/                   │
└────────────┬──────────────────────────────┬────────────────────────┘
             │                              │
             ▼                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PREPROCESSING PIPELINE                           │
│                                                                     │
│  Camera Path (6 steps):          Sensor Path (3 steps):            │
│  ┌─────────────────────┐         ┌─────────────────────┐           │
│  │ 1. Image Validation │         │ 1. Grayscale Convert│           │
│  │    Format/Size/Res  │         │ 2. Normalization    │           │
│  │    Skin Detection   │         │ 3. Noise Reduction  │           │
│  ├─────────────────────┤         │ 4. Quality Assess   │           │
│  │ 2. Region Detection │         └─────────────────────┘           │
│  │    HSV Skin Mask    │                                           │
│  │    Contour Crop     │                                           │
│  ├─────────────────────┤                                           │
│  │ 3. Normalization    │                                           │
│  │    Resize 512×512   │                                           │
│  │    CLAHE Contrast   │                                           │
│  ├─────────────────────┤                                           │
│  │ 4. Ridge Enhancement│                                           │
│  │    Gabor Bank (8θ)  │                                           │
│  ├─────────────────────┤                                           │
│  │ 5. Noise Reduction  │                                           │
│  │    Median+Gaussian  │                                           │
│  │    Morphological    │                                           │
│  ├─────────────────────┤                                           │
│  │ 6. Orientation Fix  │                                           │
│  │    Gradient-based   │                                           │
│  ├─────────────────────┤                                           │
│  │ 7. Quality Assess   │                                           │
│  │    Blur/Contrast/Edge│                                          │
│  └────────┬────────────┘                                           │
│           │ (if quality ≥ threshold)                                │
└───────────┼─────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    TEMPLATE ENGINE                                   │
│                                                                     │
│  ┌──────────────────────┐    ┌──────────────────────┐              │
│  │ Template Extraction  │    │ AES-256-CBC          │              │
│  │ Binarize → Skeleton  │───▶│ Encryption           │              │
│  │ → Minutiae Detection │    │ Random IV per record │              │
│  │ → Filter → Angles    │    └──────────┬───────────┘              │
│  └──────────────────────┘               │                          │
└─────────────────────────────────────────┼──────────────────────────┘
                                          │
                                          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PostgreSQL DATABASE                               │
│                                                                     │
│  ┌──────────────────┐          ┌──────────────────┐                │
│  │ students         │          │ medical_forms    │                │
│  │ ─────────────    │          │ ─────────────    │                │
│  │ student_id (PK)  │◄─────┐  │ form_id (PK)     │                │
│  │ registration_no  │      │  │ student_id (FK)──┘                │
│  │ full_name        │      │  │ form_pdf                          │
│  │ fingerprint_     │      │  │ uploaded_at                       │
│  │   template (enc) │      │  └──────────────────┘                │
│  │ fingerprint_hash │      │                                       │
│  │ ...              │      │                                       │
│  └──────────────────┘      │                                       │
└────────────────────────────┼────────────────────────────────────────┘
                             │
┌────────────────────────────┼────────────────────────────────────────┐
│                    MATCHING ENGINE                                   │
│                             │                                       │
│  POST /api/fingerprint/match/  or  Sensor auto-match               │
│                             │                                       │
│  ┌──────────────────────────┴──────────────────────────────┐       │
│  │  1. Decrypt stored templates                            │       │
│  │  2. Extract features: SIFT + ORB                        │       │
│  │  3. Match: BFMatcher + FLANN                            │       │
│  │  4. Lowe's ratio test (threshold 0.75)                  │       │
│  │  5. Weighted score: SIFT×0.4 + ORB×0.3 + FLANN×0.3    │       │
│  │  6. Interpretation:                                     │       │
│  │     < 20 → NO_MATCH                                     │       │
│  │     20-30 → WEAK_SIMILARITY                             │       │
│  │     30-40 → POSSIBLE_MATCH                              │       │
│  │     ≥ 40 → STRONG_MATCH                                 │       │
│  └─────────────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Hardware Layer

### 3.1 Components

| Component | Specification | Role |
|-----------|---------------|------|
| **ESP32** | WiFi-enabled microcontroller | Captures fingerprint, communicates with server |
| **AS608/R503/R307** | Optical fingerprint sensor, 288×256 resolution | Captures raw fingerprint image |
| **Touch sensor** | Capacitive, GPIO4 | Triggers capture on finger touch |
| **WiFi** | 802.11 b/g/n | Transmits image to Django server |

### 3.2 ESP32 Firmware Workflow (`esp32_as608.ino`)

```
Power On
    │
    ▼
┌──────────────┐
│ Initialize    │
│ • Serial      │ (115200 baud debug)
│ • WiFi connect│ (WPA2)
│ • AS608 UART  │ (57600 baud, GPIO16/17)
│ • Touch ISR   │ (GPIO4, rising edge)
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────┐
│            MAIN LOOP                     │
│                                          │
│  Touch detected? ──Yes──┐                │
│       │                 │                │
│       No           ┌────▼─────┐          │
│       │            │ Capture  │          │
│       │            │ Finger   │          │
│       │            │ (CMD 0x01)│         │
│       │            └────┬─────┘          │
│       │                 │                │
│       │            ┌────▼─────┐          │
│       │            │ Read     │          │
│       │            │ Image    │          │
│       │            │ Buffer   │          │
│       │            │ (36864B) │          │
│       │            └────┬─────┘          │
│       │                 │                │
│       │            ┌────▼─────┐          │
│       │            │ HTTP POST│          │
│       │            │ to Server│          │
│       │            │ (WiFi)   │          │
│       │            └──────────┘          │
│       │                                  │
│  Serial command? ──Yes──┐               │
│       │                 │               │
│       No           'c' → manual capture │
│                    'ip=' → change server │
└──────────────────────────────────────────┘
```

### 3.3 AS608 Protocol Communication

The ESP32 communicates with the AS608 sensor using a binary packet protocol:

- **Header**: `0xEF 0x01` + 4-byte module address
- **Packet ID**: `0x01` (command), `0x07` (acknowledgement), `0x02` (data), `0x08` (end of data)
- **Commands**:
  - `0x01` — Capture finger image (with LED)
  - `0x52` — Capture finger image (LED off)
  - `0x0A` — Read image from buffer
- **Image**: 288×256 pixels, 4-bit grayscale = 36,864 bytes
- **Data transfer**: Split into 128-byte packets with checksum verification

### 3.4 Data Upload

The captured image is sent as raw binary via HTTP POST:

```
POST http://<server_ip>:8000/api/fingerprint/sensor-capture/
Content-Type: application/octet-stream

<36864 bytes of raw fingerprint image data>
```

The server responds with a JSON verification result including match status and student identification.

---

## 4. Backend

### 4.1 Technology

- **Framework**: Django 4.2+ with Django REST Framework 3.14+
- **Language**: Python 3.13
- **Server**: Django development server (WSGI)
- **CORS**: django-cors-headers for frontend communication

### 4.2 Project Structure

```
fingerprint_project/
├── fingerprint_project/          # Django project configuration
│   ├── settings.py               # Database, DRF, fingerprint config, logging
│   ├── urls.py                   # Root URL routing → /api/, /admin/
│   ├── wsgi.py                   # WSGI entry point
│   └── asgi.py                   # ASGI entry point
├── fingerprint/                  # Main application
│   ├── models.py                 # Student, MedicalForm ORM models
│   ├── views.py                  # API view functions and classes
│   ├── serializers.py            # DRF request/response validation
│   ├── urls.py                   # App URL patterns
│   ├── admin.py                  # Django admin registration
│   ├── apps.py                   # App configuration
│   ├── preprocessing/            # Image processing pipeline
│   │   ├── validator.py          # Input validation
│   │   ├── region_detector.py    # Fingerprint region isolation
│   │   ├── normalizer.py         # Size/contrast normalization
│   │   ├── ridge_enhancer.py     # Gabor filter enhancement
│   │   ├── noise_reducer.py      # Artifact removal
│   │   ├── orientation.py        # Rotation correction
│   │   ├── quality.py            # Quality scoring
│   │   └── pipeline.py           # Pipeline orchestrator
│   ├── templates_engine/         # Biometric template handling
│   │   ├── extractor.py          # Minutiae extraction
│   │   ├── encryption.py         # AES-256-CBC encryption
│   │   └── matcher.py            # Multi-algorithm matching
│   └── utils/
│       └── logger.py             # Structured biometric logging
└── manage.py                     # Django management CLI
```

### 4.3 Key Configuration (`settings.py`)

```python
FINGERPRINT = {
    'MIN_IMAGE_WIDTH': 800,           # Minimum camera image width
    'MIN_IMAGE_HEIGHT': 800,          # Minimum camera image height
    'MAX_FILE_SIZE_MB': 10,           # Maximum upload size
    'NORMALIZED_SIZE': (512, 512),    # Standard processing resolution
    'ACCEPTED_FORMATS': ['JPEG', 'PNG'],
    'MATCH_THRESHOLD': 30,            # Score threshold for positive match
    'QUALITY_THRESHOLD': 40,          # Minimum quality score to accept
    'ENCRYPTION_KEY': '<from .env>',  # AES-256 key (64 hex chars)
}
```

### 4.4 Request Processing Flow

Every API request follows this lifecycle:

```
Client Request (HTTP)
    │
    ▼
┌──────────────────────────┐
│ Django Middleware Stack   │
│ • CORS headers           │
│ • Security               │
│ • Session                │
│ • CSRF                   │
│ • Authentication         │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ URL Router               │
│ /api/ → fingerprint.urls │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ DRF Parser               │
│ • JSONParser             │
│ • MultiPartParser        │
│ • FormParser             │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ Serializer Validation    │
│ • Field types            │
│ • Required fields        │
│ • Choice validation      │
│ • Custom validators      │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ View Logic               │
│ • Business logic         │
│ • Preprocessing pipeline │
│ • Template extraction    │
│ • Database operations    │
│ • Matching engine        │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ DRF Renderer             │
│ • JSONRenderer           │
│ • BrowsableAPIRenderer    │
└───────────┬──────────────┘
            │
            ▼
    JSON Response
```

---

## 5. Database

### 5.1 Technology

- **RDBMS**: PostgreSQL
- **Connection**: psycopg2-binary driver
- **ORM**: Django ORM

### 5.2 Entity Relationship Diagram

```
┌─────────────────────────────────────────────────┐
│                  students                        │
├─────────────────────────────────────────────────┤
│ student_id          SERIAL        PRIMARY KEY   │
│ registration_no     VARCHAR(50)   UNIQUE        │
│ full_name           VARCHAR(150)                │
│ date_of_birth       DATE          NULLABLE      │
│ gender              VARCHAR(10)                 │
│ college_name        VARCHAR(150)                │
│ email               VARCHAR(150)                │
│ phone               VARCHAR(20)                 │
│ photo               BYTEA         NULLABLE      │
│ fingerprint_template BYTEA        (encrypted)   │
│ fingerprint_hash    VARCHAR(64)   (SHA-256)     │
│ consent_signed      BOOLEAN       DEFAULT TRUE  │
│ created_at          TIMESTAMP     AUTO          │
│ updated_at          TIMESTAMP     AUTO          │
├─────────────────────────────────────────────────┤
│ Index: registration_no (unique)                 │
│ Order: -created_at (newest first)               │
└──────────────────┬──────────────────────────────┘
                   │
                   │ 1:N
                   │
┌──────────────────▼──────────────────────────────┐
│                medical_forms                     │
├─────────────────────────────────────────────────┤
│ form_id             SERIAL        PRIMARY KEY   │
│ student_id          INT           FOREIGN KEY   │
│ form_pdf            BYTEA                       │
│ uploaded_at         TIMESTAMP     AUTO          │
├─────────────────────────────────────────────────┤
│ FK: student_id → students(student_id)           │
│     ON DELETE CASCADE                           │
│ Order: -uploaded_at (newest first)              │
└─────────────────────────────────────────────────┘
```

### 5.3 Data Storage Strategy

| Data Type | Storage Method | Notes |
|-----------|---------------|-------|
| Student metadata | PostgreSQL columns | Standard indexed fields |
| Fingerprint template | `BYTEA` (binary) | AES-256-CBC encrypted, max 4KB |
| Template integrity | `VARCHAR(64)` | SHA-256 hash of raw template |
| Student photo | `BYTEA` (binary) | Optional, stored as binary |
| Medical form PDF | `BYTEA` (binary) | Full PDF binary stored |

### 5.4 Key Design Decisions

- **Templates stored encrypted**: The raw biometric template never exists in the database. Only the AES-256-CBC encrypted version is persisted.
- **Hash for integrity**: The `fingerprint_hash` field stores a SHA-256 hash of the raw template bytes, allowing integrity verification after decryption.
- **Cascade delete**: Deleting a student automatically removes all associated medical forms.
- **No raw images stored**: Only extracted templates are stored, not the original fingerprint images.

---

## 6. Image Preprocessing Pipeline

### 6.1 Pipeline Overview

The system uses two distinct preprocessing paths based on the input source:

| Step | Camera Path | Sensor Path |
|------|-------------|-------------|
| 1 | Format/size/resolution validation | Grayscale conversion |
| 2 | HSV skin detection + contour crop | Normalization (512×512 + CLAHE) |
| 3 | Normalization (512×512 + CLAHE) | Noise reduction (light) |
| 4 | Ridge enhancement (Gabor bank) | Quality assessment |
| 5 | Noise reduction (full) | — |
| 6 | Orientation correction | — |
| 7 | Quality assessment | — |

Camera images require the full pipeline because they contain background noise, variable lighting, and uncontrolled orientation. Sensor images are already well-captured by the hardware, so only essential normalization and cleanup are applied.

### 6.2 Module Details

#### 6.2.1 Validator (`validator.py`)

**Purpose**: Gate-keeper that rejects unsuitable images before processing.

**Checks performed**:
1. **File size**: Must be > 0 bytes and ≤ 10 MB
2. **Format**: Must be JPEG or PNG (verified via PIL `Image.verify()`)
3. **Resolution**: Must be ≥ 800×800 pixels
4. **Finger presence**: HSV skin color segmentation
   - Converts image to HSV color space
   - Applies skin color mask (hue 0–20 and 170–180, saturation > 20, value > 70)
   - Requires ≥ 10% skin-colored pixels

**Custom exception**: `ValidationError` raised with descriptive message on failure.

#### 6.2.2 Region Detector (`region_detector.py`)

**Purpose**: Isolates the fingerprint area from the full camera photo.

**Algorithm**:
1. Convert to HSV and apply dual skin color masks (light and dark skin tones)
2. Clean mask with morphological close + open operations (11×11 elliptical kernel)
3. Detect edges using Canny (thresholds 50–150)
4. Find external contours in the skin mask
5. Select the largest contour as the finger region
6. Reject if contour area < 5% of image (fallback to full image)
7. Crop with 20px padding around the bounding rectangle

**Output**: Cropped grayscale image of the fingerprint region.

#### 6.2.3 Normalizer (`normalizer.py`)

**Purpose**: Standardizes image size and contrast for consistent downstream processing.

**Operations**:
1. Convert to grayscale (if color input)
2. Resize to 512×512 using cubic interpolation (`cv2.INTER_CUBIC`)
3. Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
   - Clip limit: 2.0
   - Tile grid: 8×8
   - Enhances local contrast while preventing over-saturation
4. Normalize intensity to full [0, 255] range using min-max normalization

**Output**: 512×512 grayscale image with enhanced contrast.

#### 6.2.4 Ridge Enhancer (`ridge_enhancer.py`)

**Purpose**: Enhances fingerprint ridge structures for better minutiae detection.

**Primary method**: `fingerprint_enhancer` library (external Gabor-based enhancement)

**Fallback method**: Manual Gabor filter bank
- **8 orientations**: 0°, 22.5°, 45°, 67.5°, 90°, 112.5°, 135°, 157.5°
- **Filter parameters**:
  - Kernel size: 31×31
  - Sigma: 4.0
  - Lambda (wavelength): 9.0 (corresponding to ~1/9 ridge frequency at 500 DPI)
  - Gamma (aspect ratio): 0.5
  - Psi (phase): 0
- **Combination**: Maximum response across all 8 orientations
- **Binarization**: Otsu's thresholding

**Output**: Binary ridge-enhanced image.

#### 6.2.5 Noise Reducer (`noise_reducer.py`)

**Purpose**: Removes artifacts while preserving ridge structures.

**Steps**:
1. **Median filter** (3×3): Removes salt-and-pepper noise, preserves edges
2. **Adaptive Gaussian smoothing** (3×3, σ=0.8): Applied only if Laplacian-based noise estimate > 15
3. **Morphological opening** (3×3 elliptical kernel): Removes small isolated noise pixels
4. **Morphological closing** (3×3 elliptical kernel): Fills small gaps in ridges

**Noise estimation**: Uses Laplacian variance — higher variance indicates more noise or detail.

**Output**: Cleaned grayscale image.

#### 6.2.6 Orientation Normalizer (`orientation.py`)

**Purpose**: Corrects fingerprint rotation to a canonical alignment.

**Algorithm**:
1. Compute Sobel gradients (x and y) across the image
2. Divide image into 16×16 pixel blocks
3. For each block, compute local ridge orientation using:
   - `vx = 2 × Σ(gx × gy)`
   - `vy = Σ(gx² - gy²)`
   - `θ = 0.5 × arctan2(vx, vy)`
4. Compute weighted circular mean of all block orientations (weighted by gradient magnitude)
5. Calculate rotation needed to align dominant orientation to 90° (horizontal ridges)
6. Rotate image using affine transformation if correction > 5°

**Output**: Rotation-corrected grayscale image.

#### 6.2.7 Quality Assessor (`quality.py`)

**Purpose**: Scores fingerprint image quality and rejects poor captures.

**Three metrics** (each normalized to 0–100):

| Metric | Method | Weight | Interpretation |
|--------|--------|--------|----------------|
| **Blur score** | Laplacian variance | 35% | Higher variance = sharper |
| **Contrast score** | Local standard deviation (15×15 window) | 35% | Higher local std = better ridge contrast |
| **Edge density** | Canny edge ratio | 30% | Ideal ratio: 5–15% edges |

**Overall score**: Weighted average of the three metrics.

**Acceptance threshold**: Overall score ≥ 40 (configurable via `QUALITY_THRESHOLD`).

**Output**: `QualityResult` object with individual scores, overall score, and accept/reject decision.

### 6.3 Pipeline Orchestrator (`pipeline.py`)

Chains the modules into two executable pipelines:

**Camera pipeline** (`preprocess_camera_image`):
```
Region Detection → Normalization → Ridge Enhancement →
Noise Reduction → Orientation Correction → Quality Assessment
```

**Sensor pipeline** (`preprocess_sensor_image`):
```
Grayscale Conversion → Normalization → Noise Reduction → Quality Assessment
```

Both return a `PreprocessingResult` containing:
- `processed_image`: Final numpy array ready for template extraction
- `quality_result`: Quality assessment scores
- `steps_completed`: List of step names executed

---

## 7. Biometric Template Engine

### 7.1 Template Extraction (`extractor.py`)

**Purpose**: Converts a preprocessed fingerprint image into a compact, matchable biometric template.

#### Extraction Algorithm

```
Preprocessed Image (512×512 grayscale)
    │
    ▼
┌──────────────────────────┐
│ 1. Adaptive Thresholding │
│    Gaussian, block=11,   │
│    C=2                   │
│    → Binary image        │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ 2. Skeletonization       │
│    Thin ridges to 1px    │
│    (skimage.morphology   │
│     or OpenCV thinning)  │
│    → Skeleton image      │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ 3. Minutiae Detection    │
│    Scan 3×3 neighborhood │
│    of each ridge pixel:  │
│    • 1 neighbor → ending │
│    • 3 neighbors → bifur │
│    → Raw minutiae list   │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ 4. False Minutiae Filter │
│    • Remove border (20px)│
│    • Remove duplicates   │
│    (within 10px radius)  │
│    → Clean minutiae list │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ 5. Angle Computation     │
│    For each minutiae:    │
│    • 20×20 region around │
│    • Compute gradient    │
│    • θ = atan2(mean_gy,  │
│              mean_gx)    │
│    → Oriented minutiae   │
└───────────┬──────────────┘
            │
            ▼
┌──────────────────────────┐
│ FingerprintTemplate      │
│ • minutiae[]             │
│ • width, height          │
│ • count                  │
│ • SHA-256 hash           │
└──────────────────────────┘
```

#### Minutiae Point Structure

Each minutiae point contains:
- `x` (uint16): X-coordinate in image
- `y` (uint16): Y-coordinate in image
- `type` (uint8): 1 = ridge ending, 3 = bifurcation
- `angle` (float32): Local ridge orientation in radians

#### Binary Serialization Format

```
Header (6 bytes):
┌──────────┬──────────┬──────────┐
│ width    │ height   │ count    │
│ 2 bytes  │ 2 bytes  │ 2 bytes  │
│ uint16LE │ uint16LE │ uint16LE │
└──────────┴──────────┴──────────┘

Per minutiae (9 bytes):
┌─────┬─────┬──────┬────────┐
│ x   │ y   │ type │ angle  │
│ 2B  │ 2B  │ 1B   │ 4B     │
│ u16 │ u16 │ u8   │ float32│
└─────┴─────┴──────┴────────┘

Total: 6 + (count × 9) bytes
```

### 7.2 Template Encryption (`encryption.py`)

**Algorithm**: AES-256-CBC via `pycryptodome`

**Key management**:
- 256-bit key stored as 64-character hex string in `.env`
- If not configured, a random key is generated (development only)
- Key is loaded from Django settings on each operation

**Encryption process**:
```
Raw Template Bytes
        │
        ▼
┌──────────────────────┐
│ Generate random 16B  │
│ IV (per encryption)  │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ PKCS7 pad to 16B     │
│ block boundary       │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ AES-256-CBC encrypt  │
│ Key + IV + Padded    │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ Prepend IV to        │
│ ciphertext           │
│ → IV (16B) + Encrypted│
└──────────────────────┘
```

**Decryption**: Extract first 16 bytes as IV, decrypt remainder with same key.

**Security properties**:
- Random IV ensures identical templates produce different ciphertexts
- PKCS7 padding handles templates of any length
- No key is stored in the database

---

## 8. Fingerprint Matching Engine

### 8.1 Matching Architecture (`matcher.py`)

The matching engine uses three independent feature-matching algorithms and combines their scores:

```
Probe Image (from sensor or camera)
        │
        ▼
┌───────────────────────────────────────────────────────┐
│                                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  │
│  │    SIFT      │  │    ORB      │  │   FLANN     │  │
│  │ BFMatcher   │  │ BFMatcher   │  │ KD-Tree     │  │
│  │ NORM_L2     │  │ NORM_HAMMING│  │ SIFT-based  │  │
│  │             │  │             │  │             │  │
│  │ Score: 0-100│  │ Score: 0-100│  │ Score: 0-100│  │
│  │ Weight: 0.4 │  │ Weight: 0.3 │  │ Weight: 0.3 │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  │
│         │                │                │          │
│         └────────┬───────┴────────┬───────┘          │
│                  │                │                   │
│                  ▼                │                   │
│         ┌────────────────┐       │                   │
│         │ Weighted Score │       │                   │
│         │ SIFT×0.4 +    │       │                   │
│         │ ORB×0.3 +     │       │                   │
│         │ FLANN×0.3     │       │                   │
│         └───────┬────────┘       │                   │
│                 │                │                   │
└─────────────────┼────────────────┴───────────────────┘
                  │
                  ▼
        ┌──────────────────┐
        │ Score Interpretation │
        │ ≥ 40: STRONG_MATCH   │
        │ 30-40: POSSIBLE      │
        │ 20-30: WEAK          │
        │ < 20: NO_MATCH       │
        └──────────────────┘
```

### 8.2 Algorithm Details

#### SIFT (Scale-Invariant Feature Transform)

- **Detector**: `cv2.SIFT_create()`
- **Descriptor**: 128-dimensional floating-point vector
- **Matcher**: Brute-force with L2 norm
- **Matching**: KNN (k=2) + Lowe's ratio test (threshold 0.75)
- **Score**: `(good_matches / min(kp1_count, kp2_count)) × 100`
- **Strength**: Robust to scale and rotation changes

#### ORB (Oriented FAST and Rotated BRIEF)

- **Detector**: `cv2.ORB_create(nfeatures=1000)`
- **Descriptor**: 256-bit binary string
- **Matcher**: Brute-force with Hamming distance
- **Matching**: KNN (k=2) + Lowe's ratio test (threshold 0.75)
- **Score**: `(good_matches / min(kp1_count, kp2_count)) × 100`
- **Strength**: Fast computation, good for real-time matching

#### FLANN (Fast Library for Approximate Nearest Neighbors)

- **Detector**: SIFT features
- **Index**: KD-Tree (5 trees)
- **Search**: 50 checks
- **Matching**: KNN (k=2) + Lowe's ratio test (threshold 0.75)
- **Score**: Same normalization as SIFT
- **Strength**: Faster than brute-force for large feature sets

#### Lowe's Ratio Test

For each feature in the probe image, the two nearest neighbors in the stored template are found. A match is accepted only if:

```
distance(best_match) < 0.75 × distance(second_best_match)
```

This filters out ambiguous matches where a feature is similarly close to multiple stored features.

### 8.3 Combined Scoring

When using the `combined` method (default):

```
Final Score = (SIFT_score × 0.4) + (ORB_score × 0.3) + (FLANN_score × 0.3)
```

### 8.4 Match Thresholds

| Score Range | Interpretation | Action |
|-------------|---------------|--------|
| ≥ 40 | **STRONG_MATCH** | Identity confirmed |
| 30–39 | **POSSIBLE_MATCH** | Identity likely (default threshold) |
| 20–29 | **WEAK_SIMILARITY** | Inconclusive |
| < 20 | **NO_MATCH** | Different fingerprint |

### 8.5 Cross-Device Matching Challenge

Camera photos and sensor captures produce images with different characteristics:
- **Camera**: Color, variable lighting, background noise, perspective distortion
- **Sensor**: Grayscale, consistent lighting, clean background, fixed perspective

The preprocessing pipeline normalizes both to the same 512×512 grayscale format, enabling cross-device matching. The multi-algorithm approach provides robustness against residual differences.

---

## 9. Security & Encryption

### 9.1 Data Protection Layers

| Layer | Protection | Implementation |
|-------|-----------|----------------|
| **Transport** | HTTPS recommended | TLS 1.2+ (deployment configuration) |
| **Storage encryption** | AES-256-CBC | `pycryptodome`, random IV per template |
| **Integrity** | SHA-256 hash | Stored alongside encrypted template |
| **Key management** | Environment variable | `.env` file, never committed to VCS |
| **Logging safety** | No biometric data | `BiometricLogger` strips image/template fields |

### 9.2 Encryption Workflow

```
ENROLLMENT:
Raw Template → Serialize → AES-256-CBC Encrypt → Store (encrypted) in DB
                                                       + Store SHA-256 hash

VERIFICATION:
Probe Image → Preprocess → Extract Template
                              ↓
DB: Encrypted Template → AES-256-CBC Decrypt → Deserialize → Reconstruct Image
                              ↓
                    Match probe vs stored using SIFT/ORB/FLANN
```

### 9.3 Key Security Considerations

- The encryption key is stored as a 64-character hex string (32 bytes) in the `.env` file
- Each template encryption generates a fresh 16-byte random IV
- The `.env` file is excluded from version control via `.gitignore`
- Django `SECRET_KEY` is separate from the biometric encryption key
- No raw fingerprint images are persisted — only extracted templates

---

## 10. API Endpoints

### 10.1 Complete API Reference

| # | Endpoint | Method | Purpose | Input | Output |
|---|----------|--------|---------|-------|--------|
| 1 | `/api/health/` | GET | Health check | — | `{status, service}` |
| 2 | `/api/fingerprint/upload/` | POST | Camera photo enrollment | Multipart: student_id, finger_type, fingerprint_image | Enrollment result |
| 3 | `/api/fingerprint/sensor-capture/` | POST | Sensor verification | Raw binary image (octet-stream) | Match result + student info |
| 4 | `/api/fingerprint/match/` | POST | Manual matching | Image file or base64 + optional student_id | Match result |
| 5 | `/api/students/` | GET | List all students | — | Student list |
| 6 | `/api/students/` | POST | Create student | JSON: registration_no, full_name, etc. | Created student |
| 7 | `/api/students/<id>/` | GET | Student details | — | Student record |
| 8 | `/api/students/<id>/` | PUT | Update student | JSON: fields to update | Updated student |
| 9 | `/api/students/<id>/` | DELETE | Delete student | — | 204 No Content |
| 10 | `/api/medical-forms/` | POST | Upload medical PDF | Multipart: student_id, form_pdf | Upload confirmation |
| 11 | `/admin/` | GET | Django admin panel | Browser login | Admin interface |

### 10.2 Detailed Endpoint Flows

#### POST `/api/fingerprint/upload/` — Camera Enrollment

```
Request (multipart/form-data):
├── student_id: 1
├── finger_type: "right_index"
└── fingerprint_image: <JPEG/PNG file>

Processing:
1. Validate serializer fields
2. Check student exists in DB
3. Validate image (format, size, resolution, skin detection)
4. Preprocess: Region detect → Normalize → Enhance → Denoise → Orient → Quality check
5. IF quality < 40 → reject with quality scores
6. Extract template (skeletonize → minutiae detection)
7. IF minutiae < 5 → reject
8. Serialize template to binary
9. Encrypt with AES-256-CBC
10. Compute SHA-256 hash
11. Update student record (fingerprint_template, fingerprint_hash)
12. Log enrollment

Response (201):
{
    "message": "Fingerprint enrolled successfully",
    "student_id": 1,
    "finger_type": "right_index",
    "minutiae_count": 47,
    "quality": {
        "blur_score": 72.3,
        "contrast_score": 65.8,
        "edge_density": 81.2,
        "overall_score": 72.6,
        "is_acceptable": true
    },
    "preprocessing_steps": ["region_detection", "normalization", ...]
}
```

#### POST `/api/fingerprint/sensor-capture/` — Sensor Verification

```
Request (application/octet-stream):
<raw 36864 bytes from ESP32 AS608 sensor>

Processing:
1. Read raw binary from request body
2. Open as PIL Image
3. Preprocess: Grayscale → Normalize → Denoise → Quality check
4. Extract template from probe image
5. IF minutiae < 5 → reject
6. For each enrolled student:
   a. Decrypt stored template
   b. Deserialize to FingerprintTemplate
   c. Reconstruct image from minutiae
   d. Match probe vs stored (SIFT+ORB+FLANN combined)
   e. Track best score
7. Return match result with student info if matched

Response (200):
{
    "validated": true,
    "score": 52.3,
    "interpretation": "STRONG_MATCH",
    "minutiae_extracted": 38,
    "student_id": 1,
    "registration_no": "REG-2024-001",
    "full_name": "John Doe"
}
```

#### POST `/api/fingerprint/match/` — Manual Matching

```
Request (JSON or multipart):
{
    "fingerprint_base64": "<base64-encoded-image>",
    "student_id": 1  // optional — omit to match against all
}

Processing:
1. Decode image from file or base64
2. Preprocess (sensor path — lighter pipeline)
3. Query enrolled students (all or specific)
4. For each student:
   a. Decrypt → Deserialize → Reconstruct image
   b. Match using combined method
5. Apply threshold (≥ 30 = match found)

Response (200):
{
    "match_found": true,
    "score": 45.7,
    "method": "combined",
    "interpretation": "STRONG_MATCH",
    "student_id": 1,
    "registration_no": "REG-2024-001",
    "full_name": "John Doe"
}
```

---

## 11. Frontend

The frontend is designed as a React application running on port 3000, communicating with the Django backend via REST API calls. CORS is configured in the backend to accept requests from `http://localhost:3000`.

**Key frontend capabilities** (based on API consumption):

- **Student registration form**: Create student records with personal details
- **Fingerprint enrollment interface**: Upload camera photos for enrollment
- **Verification dashboard**: Trigger fingerprint matching and view results
- **Student list view**: Browse and manage enrolled students
- **Medical form upload**: Attach PDF medical forms to student records
- **Real-time feedback**: Display quality scores, match results, and error messages

The frontend connects to the backend at `http://localhost:8000/api/` and uses standard REST conventions (GET for reads, POST for creates, PUT for updates, DELETE for removals).

---

## 12. End-to-End Workflows

### 12.1 Enrollment Workflow (Camera)

```
User/Admin
    │
    │  1. Create student record
    ▼
POST /api/students/
{registration_no, full_name, ...}
    │
    │  2. Capture fingerprint photo
    ▼
POST /api/fingerprint/upload/
{student_id, finger_type, image}
    │
    │  3. Validation
    ▼
Format OK? ──No──→ Reject (400: invalid format)
    │ Yes
Resolution OK? ──No──→ Reject (400: too small)
    │ Yes
Skin detected? ──No──→ Reject (400: no fingerprint)
    │ Yes
    │  4. Preprocessing
    ▼
Region detect → Normalize → Enhance → Denoise → Orient
    │
    │  5. Quality check
    ▼
Score ≥ 40? ──No──→ Reject (400: poor quality)
    │ Yes
    │  6. Template extraction
    ▼
Skeletonize → Detect minutiae → Filter → Compute angles
    │
    │  7. Minutiae count check
    ▼
Count ≥ 5? ──No──→ Reject (400: too few minutiae)
    │ Yes
    │  8. Encrypt & store
    ▼
Serialize → AES-256-CBC Encrypt → Store in DB → Hash stored
    │
    ▼
Success (201): enrollment details
```

### 12.2 Verification Workflow (Sensor)

```
ESP32 Sensor
    │
    │  1. Finger placed on sensor
    ▼
Touch interrupt (GPIO4)
    │
    │  2. Capture via AS608 protocol
    ▼
CMD 0x01 → ACK → CMD 0x0A → Read 36864 bytes
    │
    │  3. Upload to server
    ▼
POST /api/fingerprint/sensor-capture/
Content-Type: application/octet-stream
<body: 36864 bytes>
    │
    │  4. Server: preprocess (light)
    ▼
Grayscale → Normalize → Denoise → Quality check
    │
    │  5. Extract probe template
    ▼
Binarize → Skeletonize → Minutiae detection
    │
    │  6. Match against all enrolled
    ▼
For each student with template:
    Decrypt → Deserialize → Reconstruct image
    SIFT match → ORB match → FLANN match
    Combined weighted score
    Track best match
    │
    │  7. Decision
    ▼
Best score ≥ 30? ──No──→ {validated: false, score: X}
    │ Yes
    ▼
{validated: true, score: X, student_id, name, registration_no}
    │
    │  8. Response to ESP32
    ▼
JSON response → Display on serial monitor
```

### 12.3 Manual Matching Workflow

```
Operator
    │
    │  Provide fingerprint image
    ▼
POST /api/fingerprint/match/
{fingerprint_image or fingerprint_base64, optional student_id}
    │
    │  Preprocess
    ▼
Light pipeline (sensor path)
    │
    │  Match
    ▼
Specific student or all enrolled
    │
    │  Result
    ▼
{match_found, score, interpretation, student details}
```

---

## 13. Technology Stack Summary

### Backend

| Technology | Version | Purpose |
|-----------|---------|---------|
| Python | 3.13 | Runtime |
| Django | 4.2+ | Web framework |
| Django REST Framework | 3.14+ | REST API |
| django-cors-headers | 4.3+ | CORS support |
| PostgreSQL | — | Database |
| psycopg2-binary | 2.9+ | PostgreSQL driver |

### Image Processing

| Technology | Version | Purpose |
|-----------|---------|---------|
| OpenCV (opencv-python) | 4.8+ | Image processing, feature detection |
| NumPy | 1.24+ | Numerical operations |
| scikit-image | 0.21+ | Skeletonization |
| fingerprint-enhancer | 0.2+ | Gabor-based ridge enhancement |
| Pillow | 10.0+ | Image I/O and validation |

### Security

| Technology | Version | Purpose |
|-----------|---------|---------|
| pycryptodome | 3.19+ | AES-256-CBC encryption |

### Hardware

| Technology | Purpose |
|-----------|---------|
| ESP32 (Arduino) | Microcontroller firmware |
| AS608/R503/R307 | Optical fingerprint sensor |
| WiFi (802.11) | Data transmission |

### Development

| Technology | Version | Purpose |
|-----------|---------|---------|
| python-dotenv | 1.0+ | Environment variable management |
| pytest | 7.4+ | Testing framework |
| pytest-django | 4.5+ | Django test integration |

---

## Appendix A: Match Score Calculation Example

Given two fingerprint images, the combined matching score is calculated as:

```
SIFT matching:
  Keypoints in image1: 156
  Keypoints in image2: 142
  KNN matches: 142 pairs
  Lowe's ratio test passes: 58 matches
  SIFT score = (58 / 142) × 100 = 40.85

ORB matching:
  Keypoints in image1: 890
  Keypoints in image2: 934
  KNN matches: 890 pairs
  Lowe's ratio test passes: 312 matches
  ORB score = (312 / 890) × 100 = 35.06

FLANN matching:
  Keypoints in image1: 156 (SIFT)
  Keypoints in image2: 142 (SIFT)
  KNN matches: 142 pairs
  Lowe's ratio test passes: 55 matches
  FLANN score = (55 / 142) × 100 = 38.73

Combined score = (40.85 × 0.4) + (35.06 × 0.3) + (38.73 × 0.3)
              = 16.34 + 10.52 + 11.62
              = 38.48

Interpretation: POSSIBLE_MATCH (30-40 range)
```

---

## Appendix B: Configuration Reference

### Environment Variables (`.env`)

| Variable | Example | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `django-insecure-...` | Django secret key |
| `DEBUG` | `True` | Debug mode |
| `SERVER_HOST` | `0.0.0.0` | Bind address |
| `SERVER_PORT` | `8000` | Server port |
| `DB_NAME` | `fingerprint_db` | Database name |
| `DB_USER` | `postgres` | Database user |
| `DB_PASSWORD` | `your-password` | Database password |
| `DB_HOST` | `localhost` | Database host |
| `DB_PORT` | `5432` | Database port |
| `ENCRYPTION_KEY` | `<64 hex chars>` | AES-256 encryption key |
| `SENSOR_ENABLED` | `True` | Enable sensor capture |

---

*Document generated from source code analysis on 2026-04-01.*
*System: Fingerprint Processing & Matching Pipeline v1.0*
