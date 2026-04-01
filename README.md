# Fingerprint Photo Processing & Matching Pipeline

A Django-based biometric pipeline for processing smartphone fingerprint photos and R503/R307 sensor captures, extracting minutiae templates, and performing cross-device matching.

## Quick Start

### 1. Setup Virtual Environment

```bash
cd f:\FingerPrint_sensor
.\venv\Scripts\activate
```

### 2. Configure Environment

Edit `.env` with your PostgreSQL credentials and encryption key:

```bash
DB_NAME=fingerprint_db
DB_USER=postgres
DB_PASSWORD=your-password
ENCRYPTION_KEY=<64-hex-char-key>
```

Generate an encryption key:
```bash
python -c "import os; print(os.urandom(32).hex())"
```

### 3. Create Database

```sql
CREATE DATABASE fingerprint_db;
```

### 4. Run Migrations

```bash
cd fingerprint_project
python manage.py makemigrations fingerprint
python manage.py migrate
python manage.py createsuperuser
```

### 5. Start Server

```bash
python manage.py runserver
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health/` | GET | Health check |
| `/api/fingerprint/upload/` | POST | Upload camera fingerprint photo |
| `/api/fingerprint/sensor-capture/` | POST | ESP32 sensor capture |
| `/api/fingerprint/match/` | POST | Match fingerprint against stored templates |
| `/api/students/` | GET/POST | List/create students |
| `/api/students/<id>/` | GET/PUT/DELETE | Student detail |
| `/api/medical-forms/` | POST | Upload medical form PDF |

## ESP32 Integration

The sensor capture endpoint accepts data from an ESP32 module connected to an R503/R307 sensor:

```json
POST /api/fingerprint/sensor-capture/
{
    "student_id": 1,
    "finger_type": "right_index",
    "fingerprint_base64": "<base64-encoded-image>"
}
```

## Matching

Uses SIFT, ORB, BFMatcher, and FLANN algorithms for cross-device fingerprint matching.

| Score | Interpretation |
|-------|---------------|
| < 20 | No match |
| 20–30 | Weak similarity |
| 30–40 | Possible match |
| ≥ 40 | Strong match |

## Project Structure

```
F:\FingerPrint_sensor\
├── .env                          # Environment variables (PostgreSQL, encryption key)
├── .env.example                  # Example environment variables template
├── .gitignore                    # Git ignore rules
├── esp32_as608\                  # ESP32 Arduino sketch for AS608/R503/R307 sensor
│   └── esp32_as608.ino           # Sensor communication firmware
├── fingerprint_project\          # Django project root
│   ├── fingerprint\              # Main Django app
│   │   ├── models.py             # Student, MedicalForm models
│   │   ├── views.py              # API endpoints
│   │   ├── urls.py               # API routing
│   │   ├── serializers.py        # DRF serializers
│   │   ├── admin.py              # Django admin configuration
│   │   ├── apps.py               # App configuration
│   │   ├── tests.py              # Test cases
│   │   ├── migrations\           # Database migrations
│   │   ├── preprocessing\        # Image processing pipeline (6 modules)
│   │   │   ├── validator.py      # Format/size/resolution validation
│   │   │   ├── region_detector.py# HSV skin detection + contour crop
│   │   │   ├── normalizer.py     # 512×512 resize + CLAHE
│   │   │   ├── ridge_enhancer.py # Gabor filter bank (8 orientations)
│   │   │   ├── noise_reducer.py  # Median + Gaussian + morphological ops
│   │   │   ├── orientation.py    # Gradient-based rotation correction
│   │   │   ├── quality.py        # Blur/contrast/edge scoring
│   │   │   └── pipeline.py       # Camera & sensor orchestrators
│   │   ├── templates_engine\     # Biometric template handling (3 modules)
│   │   │   ├── extractor.py      # Minutiae detection + binary serialization
│   │   │   ├── encryption.py     # AES-256-CBC encryption
│   │   │   └── matcher.py        # SIFT + ORB + FLANN matching
│   │   ├── utils\
│   │   │   └── logger.py         # Logging utilities
│   │   ├── static\               # Static files
│   │   └── templates\            # Django templates
│   ├── fingerprint_project\      # Django project settings
│   │   ├── settings.py           # Settings (PostgreSQL + DRF config)
│   │   ├── urls.py               # Root URL configuration
│   │   ├── asgi.py               # ASGI entry point
│   │   └── wsgi.py               # WSGI entry point
│   ├── manage.py                 # Django management script
│   └── fingerprint.log           # Application log file
├── tests\                        # Test directory
├── sample_data\                  # Sample fingerprint data
├── requirements.txt              # Python dependencies
├── README.md                     # This file
└── walkthrough.md                # Detailed implementation walkthrough
```
