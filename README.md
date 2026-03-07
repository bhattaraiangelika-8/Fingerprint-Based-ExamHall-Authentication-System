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
fingerprint_project/
├── fingerprint/            # Django app
│   ├── models.py           # Student, MedicalForm
│   ├── views.py            # API endpoints
│   ├── urls.py             # Routing
│   ├── serializers.py      # DRF serializers
│   ├── preprocessing/      # Image processing pipeline
│   │   ├── validator.py
│   │   ├── region_detector.py
│   │   ├── normalizer.py
│   │   ├── ridge_enhancer.py
│   │   ├── noise_reducer.py
│   │   ├── orientation.py
│   │   ├── quality.py
│   │   └── pipeline.py
│   ├── templates_engine/   # Biometric template handling
│   │   ├── extractor.py
│   │   ├── encryption.py
│   │   └── matcher.py
│   └── utils/
│       └── logger.py
└── fingerprint_project/    # Django settings
```
