"""
Fingerprint API Views
─────────────────────
Django REST Framework views for fingerprint upload, sensor capture,
matching, student CRUD, and health check.
"""

import io
import os
import base64
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from django.views.generic import TemplateView
from rest_framework import status, generics
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

from .models import Student, MedicalForm
from .serializers import (
    StudentSerializer,
    StudentCreateSerializer,
    FingerprintUploadSerializer,
    MatchRequestSerializer,
    MedicalFormUploadSerializer,
)
from .preprocessing.validator import validate_image, ValidationError
from .preprocessing.pipeline import preprocess_camera_image
from .templates_engine.extractor import extract_template
from .templates_engine.encryption import encrypt_template
from .templates_engine.matcher import match_fingerprints

logger = logging.getLogger('fingerprint')

# Directory for saving captured fingerprint images for visual inspection
CAPTURE_DIR = Path(__file__).resolve().parent.parent / 'captured_fingerprints'
CAPTURE_DIR.mkdir(exist_ok=True)


def _save_fingerprint_image(image_array, prefix, student_id=None, mode='L'):
    """
    Save a fingerprint image as PNG for visual inspection.

    Args:
        image_array: numpy array (grayscale or RGB)
        prefix: 'sensor_raw', 'sensor_processed', 'enrolled', 'enrolled_original'
        student_id: optional student ID for filename
        mode: 'L' for grayscale, 'RGB' for color
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    student_part = f"_student{student_id}" if student_id else ""
    filename = f"{prefix}{student_part}_{timestamp}.png"
    filepath = CAPTURE_DIR / filename

    img = Image.fromarray(image_array, mode=mode)
    img.save(str(filepath))

    logger.info("Saved %s fingerprint image to %s", prefix, filepath)
    return str(filepath)


# ──────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────

@api_view(['GET'])
def health_check(request):
    """Health check endpoint."""
    return Response({
        'status': 'healthy',
        'service': 'fingerprint-processing-pipeline',
    })


# ──────────────────────────────────────────────
# Fingerprint Upload (Camera Photo)
# ──────────────────────────────────────────────

@api_view(['POST'])
def fingerprint_upload(request):
    """
    POST /api/fingerprint/upload/

    Upload a camera-captured fingerprint photo. The image goes through
    the full preprocessing pipeline, template extraction, encryption,
    and storage.
    """
    serializer = FingerprintUploadSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    student_id = serializer.validated_data['student_id']
    finger_type = serializer.validated_data['finger_type']
    image_file = serializer.validated_data['fingerprint_image']

    # ── Verify student exists ──
    try:
        student = Student.objects.get(student_id=student_id)
    except Student.DoesNotExist:
        return Response(
            {'error': f'Student with id {student_id} not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # ── Validate image ──
    try:
        pil_image = validate_image(image_file)
    except ValidationError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Save original uploaded camera photo for visual inspection
    img_array_gray = np.array(pil_image.convert('L'))
    _save_fingerprint_image(img_array_gray, 'enrolled_original', student_id)

    # ── Preprocess with camera pipeline (aggressive normalization) ──
    img_array = np.array(pil_image.convert('RGB'))
    result = preprocess_camera_image(img_array)

    # Save preprocessed enrolled image for visual inspection
    _save_fingerprint_image(result.processed_image, 'enrolled', student_id)

    # ── Quality check ──
    if not result.quality_result.is_acceptable:
        return Response({
            'error': 'Fingerprint image quality insufficient',
            'quality': result.quality_result.to_dict(),
        }, status=status.HTTP_400_BAD_REQUEST)

    # ── Extract template ──
    template = extract_template(result.processed_image)

    if template.count < 5:
        return Response({
            'error': 'Too few minutiae detected. Please capture a clearer fingerprint.',
            'minutiae_count': template.count,
        }, status=status.HTTP_400_BAD_REQUEST)

    # ── Encrypt and store ──
    template_bytes = template.serialize()
    encrypted = encrypt_template(template_bytes)
    template_hash = template.compute_hash()

    # Store processed image for matching
    processed_image_bytes = result.processed_image.tobytes()

    # Update student's fingerprint data
    student.fingerprint_template = encrypted
    student.fingerprint_hash = template_hash
    student.fingerprint_image = processed_image_bytes
    student.save()

    logger.info(
        "Fingerprint enrolled: student_id=%s, finger=%s, minutiae=%d, quality=%.1f",
        student_id, finger_type, template.count,
        result.quality_result.overall_score,
    )

    return Response({
        'message': 'Fingerprint enrolled successfully',
        'student_id': student_id,
        'finger_type': finger_type,
        'minutiae_count': template.count,
        'quality': result.quality_result.to_dict(),
        'preprocessing_steps': result.steps_completed,
    }, status=status.HTTP_201_CREATED)


# ──────────────────────────────────────────────
# ESP32 Sensor Capture Endpoint
# ──────────────────────────────────────────────

@api_view(['POST'])
def sensor_capture(request):
    """
    POST /api/fingerprint/sensor-capture/

    Receives raw fingerprint image from an ESP32 module connected to
    an AS608/R503/R307 sensor. Extracts the template and matches
    against all enrolled fingerprints. Returns student info on match.

    Request body: raw binary image data (application/octet-stream)
    The AS608 sensor outputs 256×288 images at 4 bits per pixel,
    packed as 2 pixels per byte (high nibble first), totalling 36864 bytes.
    """
    # ── Read raw binary from ESP32 ──
    image_bytes = request.body

    if not image_bytes or len(image_bytes) < 100:
        return Response(
            {'error': 'No image data received or data too small'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # ── Convert to PIL Image ──
    try:
        pil_image = _parse_sensor_image(image_bytes)
    except Exception as e:
        return Response(
            {'error': f'Invalid image data: {e}'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Save raw sensor capture for visual inspection
    img_array_raw = np.array(pil_image.convert('L'))
    _save_fingerprint_image(img_array_raw, 'sensor_raw')

    # ── Preprocess sensor image (full camera pipeline for better matching) ──
    img_array = np.array(pil_image.convert('RGB'))  # Convert to RGB for camera pipeline
    result = preprocess_camera_image(img_array)

    # Save preprocessed sensor image for visual inspection
    _save_fingerprint_image(result.processed_image, 'sensor_processed')

    # ── Extract template from probe image ──
    template = extract_template(result.processed_image)

    if template.count < 5:
        return Response({
            'validated': False,
            'error': 'Poor fingerprint quality — too few minutiae detected',
            'minutiae_count': template.count,
        }, status=status.HTTP_400_BAD_REQUEST)

    # ── Match against all enrolled fingerprints ──
    match_result, matched_student_id = _match_against_enrolled(result.processed_image)

    is_validated = match_result.is_match if match_result else False

    response_data = {
        'validated': is_validated,
        'score': round(match_result.score, 2) if match_result else 0,
        'interpretation': match_result.interpretation if match_result else 'NO_MATCH',
        'minutiae_extracted': template.count,
    }

    if is_validated and matched_student_id:
        try:
            student = Student.objects.get(student_id=matched_student_id)
            response_data['student_id'] = student.student_id
            response_data['registration_no'] = student.registration_no
            response_data['full_name'] = student.full_name
        except Student.DoesNotExist:
            response_data['validated'] = False

    logger.info(
        "Sensor verification: validated=%s, score=%.2f, student_id=%s",
        is_validated,
        match_result.score if match_result else 0,
        matched_student_id,
    )

    return Response(response_data)


def _match_against_enrolled(probe_image):
    """
    Match a probe fingerprint image against all enrolled templates.

    Returns:
        tuple[MatchResult | None, int | None]: (best match result, matched student_id)
    """
    students = Student.objects.exclude(
        fingerprint_template=b''
    ).exclude(
        fingerprint_template__isnull=True
    ).exclude(
        fingerprint_image__isnull=True
    )

    if not students.exists():
        return None, None

    best_score = 0
    best_student_id = None
    best_result = None

    for student in students:
        if not student.fingerprint_template or not student.fingerprint_image:
            continue

        try:
            # Use stored preprocessed image directly for matching
            stored_image = np.frombuffer(
                bytes(student.fingerprint_image), dtype=np.uint8
            ).reshape((512, 512))

            result = match_fingerprints(probe_image, stored_image, method='combined')

            if result.score > best_score:
                best_score = result.score
                best_student_id = student.student_id
                best_result = result

        except Exception as e:
            logger.warning("Error matching student %s: %s", student.student_id, e)
            continue

    return best_result, best_student_id


def _parse_sensor_image(image_bytes):
    """
    Parse raw fingerprint sensor data into a PIL Image.

    The AS608/R503/R307 sensors output a 256×288 image at 4 bits per pixel,
    packed as 2 pixels per byte (high nibble = first pixel, low nibble = second).
    Total size: 256 * 288 / 2 = 36864 bytes.

    Each 4-bit value (0–15) is scaled to 8-bit (0–255) by multiplying by 17.

    Falls back to PIL's Image.open() for standard image formats (e.g. BMP/PNG).
    """
    AS608_IMAGE_WIDTH  = 256
    AS608_IMAGE_HEIGHT = 288
    AS608_RAW_SIZE     = AS608_IMAGE_WIDTH * AS608_IMAGE_HEIGHT // 2  # 36864

    if len(image_bytes) == AS608_RAW_SIZE:
        # Unpack 4-bit-per-pixel raw sensor data
        raw = np.frombuffer(image_bytes, dtype=np.uint8)
        # High nibble → first pixel, low nibble → second pixel
        high = (raw >> 4) & 0x0F
        low  = raw & 0x0F
        # Interleave: [h0, l0, h1, l1, ...]
        pixels = np.empty(AS608_IMAGE_WIDTH * AS608_IMAGE_HEIGHT, dtype=np.uint8)
        pixels[0::2] = high
        pixels[1::2] = low
        # Scale 4-bit (0–15) to 8-bit (0–255)
        pixels = (pixels * 17).astype(np.uint8)
        img_array = pixels.reshape((AS608_IMAGE_HEIGHT, AS608_IMAGE_WIDTH))
        return Image.fromarray(img_array, mode='L')
    else:
        # Fallback: try to open as a standard image format
        return Image.open(io.BytesIO(image_bytes))


# ──────────────────────────────────────────────
# Template Matching
# ──────────────────────────────────────────────

@api_view(['POST'])
def fingerprint_match(request):
    """
    POST /api/fingerprint/match/

    Match an incoming fingerprint against stored templates.
    Can match against all students or a specific student.
    """
    serializer = MatchRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ── Get probe image ──
    if serializer.validated_data.get('fingerprint_image'):
        image_file = serializer.validated_data['fingerprint_image']
        pil_image = Image.open(image_file)
    elif serializer.validated_data.get('fingerprint_base64'):
        try:
            b64_data = serializer.validated_data['fingerprint_base64']
            image_bytes = base64.b64decode(b64_data)
            pil_image = Image.open(io.BytesIO(image_bytes))
        except Exception as e:
            return Response(
                {'error': f'Invalid base64 image data: {e}'},
                status=status.HTTP_400_BAD_REQUEST
            )
    else:
        return Response(
            {'error': 'No image data provided'},
            status=status.HTTP_400_BAD_REQUEST
        )

    # ── Preprocess probe image ──
    img_array = np.array(pil_image.convert('RGB'))
    result = preprocess_camera_image(img_array)
    probe_image = result.processed_image

    # ── Get stored templates ──
    specific_student_id = serializer.validated_data.get('student_id')

    if specific_student_id:
        students = Student.objects.filter(student_id=specific_student_id)
    else:
        students = Student.objects.exclude(fingerprint_template=b'').exclude(fingerprint_image__isnull=True)

    if not students.exists():
        return Response({
            'match_found': False,
            'error': 'No enrolled fingerprints found',
        }, status=status.HTTP_404_NOT_FOUND)

    # ── Match against stored images ──
    best_score = 0
    best_student = None
    best_method = 'combined'

    for student in students:
        if not student.fingerprint_template or not student.fingerprint_image:
            continue

        try:
            # Use stored preprocessed image directly for matching
            stored_image = np.frombuffer(
                bytes(student.fingerprint_image), dtype=np.uint8
            ).reshape((512, 512))

            match_result = match_fingerprints(probe_image, stored_image, method='combined')

            if match_result.score > best_score:
                best_score = match_result.score
                best_student = student
                best_method = match_result.method

        except Exception as e:
            logger.warning(
                "Error matching student %s: %s", student.student_id, e
            )
            continue

    # ── Build response ──
    is_match = best_score >= 30  # Default threshold

    response_data = {
        'match_found': is_match,
        'score': round(best_score, 2),
        'method': best_method,
        'interpretation': _get_interpretation(best_score),
    }

    if is_match and best_student:
        response_data['student_id'] = best_student.student_id
        response_data['registration_no'] = best_student.registration_no
        response_data['full_name'] = best_student.full_name

    logger.info(
        "Match result: found=%s, score=%.2f, student=%s",
        is_match, best_score,
        best_student.student_id if best_student else None,
    )

    return Response(response_data)


def _get_interpretation(score):
    """Get human-readable interpretation of match score."""
    if score < 20:
        return 'NO_MATCH'
    elif score < 30:
        return 'WEAK_SIMILARITY'
    elif score < 40:
        return 'POSSIBLE_MATCH'
    else:
        return 'STRONG_MATCH'


# ──────────────────────────────────────────────
# Student CRUD
# ──────────────────────────────────────────────

class StudentListCreateView(generics.ListCreateAPIView):
    """
    GET /api/students/ — List all students
    POST /api/students/ — Create a new student
    """
    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return StudentCreateSerializer
        return StudentSerializer

    def perform_create(self, serializer):
        # Save with empty fingerprint (enrolled later via upload)
        student = serializer.save(
            fingerprint_template=b'',
            fingerprint_hash='',
        )
        logger.info("Student created: id=%s, reg=%s",
                     student.student_id, student.registration_no)


class StudentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET /api/students/<id>/ — Get student details
    PUT /api/students/<id>/ — Update student
    DELETE /api/students/<id>/ — Delete student
    """
    queryset = Student.objects.all()
    serializer_class = StudentSerializer
    lookup_field = 'student_id'


# ──────────────────────────────────────────────
# Medical Form Upload
# ──────────────────────────────────────────────

@api_view(['POST'])
def medical_form_upload(request):
    """
    POST /api/medical-forms/

    Upload a medical form PDF for a student.
    """
    serializer = MedicalFormUploadSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    student_id = serializer.validated_data['student_id']
    form_pdf = serializer.validated_data['form_pdf']

    try:
        student = Student.objects.get(student_id=student_id)
    except Student.DoesNotExist:
        return Response(
            {'error': f'Student with id {student_id} not found'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Read PDF bytes
    pdf_bytes = form_pdf.read()

    medical_form = MedicalForm.objects.create(
        student=student,
        form_pdf=pdf_bytes,
    )

    logger.info(
        "Medical form uploaded: form_id=%s, student_id=%s, size=%d bytes",
        medical_form.form_id, student_id, len(pdf_bytes),
    )

    return Response({
        'message': 'Medical form uploaded successfully',
        'form_id': medical_form.form_id,
        'student_id': student_id,
    }, status=status.HTTP_201_CREATED)
