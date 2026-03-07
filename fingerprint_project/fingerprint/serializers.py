"""
DRF Serializers for Fingerprint API
────────────────────────────────────
"""

import base64
from rest_framework import serializers
from .models import Student, MedicalForm


class StudentSerializer(serializers.ModelSerializer):
    """Serializer for Student model."""

    class Meta:
        model = Student
        fields = [
            'student_id', 'registration_no', 'full_name',
            'date_of_birth', 'gender', 'college_name',
            'email', 'phone', 'consent_signed',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['student_id', 'created_at', 'updated_at']


class StudentCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating a student with fingerprint enrollment."""

    photo = serializers.ImageField(required=False)
    fingerprint_image = serializers.ImageField(write_only=True)

    class Meta:
        model = Student
        fields = [
            'registration_no', 'full_name', 'date_of_birth',
            'gender', 'college_name', 'email', 'phone',
            'photo', 'fingerprint_image', 'consent_signed',
        ]


class MedicalFormSerializer(serializers.ModelSerializer):
    """Serializer for MedicalForm model."""

    class Meta:
        model = MedicalForm
        fields = ['form_id', 'student_id', 'uploaded_at']
        read_only_fields = ['form_id', 'uploaded_at']


class MedicalFormUploadSerializer(serializers.Serializer):
    """Serializer for medical form PDF upload."""

    student_id = serializers.IntegerField()
    form_pdf = serializers.FileField()


class FingerprintUploadSerializer(serializers.Serializer):
    """Serializer for fingerprint camera photo upload."""

    student_id = serializers.IntegerField()
    finger_type = serializers.ChoiceField(
        choices=['left_thumb', 'left_index', 'left_middle', 'left_ring', 'left_pinky',
                 'right_thumb', 'right_index', 'right_middle', 'right_ring', 'right_pinky'],
        default='right_index'
    )
    fingerprint_image = serializers.ImageField()


class SensorCaptureSerializer(serializers.Serializer):
    """
    Serializer for ESP32 sensor capture data.
    The ESP32 sends the fingerprint image as base64 or file.
    """

    student_id = serializers.IntegerField()
    finger_type = serializers.ChoiceField(
        choices=['left_thumb', 'left_index', 'left_middle', 'left_ring', 'left_pinky',
                 'right_thumb', 'right_index', 'right_middle', 'right_ring', 'right_pinky'],
        default='right_index'
    )
    # Accept either image file or base64-encoded image from ESP32
    fingerprint_image = serializers.ImageField(required=False)
    fingerprint_base64 = serializers.CharField(required=False)

    def validate(self, data):
        if not data.get('fingerprint_image') and not data.get('fingerprint_base64'):
            raise serializers.ValidationError(
                "Either 'fingerprint_image' or 'fingerprint_base64' must be provided."
            )
        return data


class MatchRequestSerializer(serializers.Serializer):
    """Serializer for fingerprint match request."""

    fingerprint_image = serializers.ImageField(required=False)
    fingerprint_base64 = serializers.CharField(required=False)
    student_id = serializers.IntegerField(
        required=False,
        help_text="Optional: Match against a specific student only."
    )

    def validate(self, data):
        if not data.get('fingerprint_image') and not data.get('fingerprint_base64'):
            raise serializers.ValidationError(
                "Either 'fingerprint_image' or 'fingerprint_base64' must be provided."
            )
        return data


class MatchResponseSerializer(serializers.Serializer):
    """Serializer for match result response."""

    match_found = serializers.BooleanField()
    score = serializers.FloatField()
    interpretation = serializers.CharField()
    method = serializers.CharField()
    student_id = serializers.IntegerField(allow_null=True)
    registration_no = serializers.CharField(allow_null=True)
    full_name = serializers.CharField(allow_null=True)


class QualityResponseSerializer(serializers.Serializer):
    """Quality assessment response."""

    blur_score = serializers.FloatField()
    contrast_score = serializers.FloatField()
    edge_density = serializers.FloatField()
    overall_score = serializers.FloatField()
    is_acceptable = serializers.BooleanField()
