"""
DRF Serializers for Fingerprint API
"""
import base64
from rest_framework import serializers
from .models import (
    Student, Subject, ExamCenter, Hall, Exam,
    SeatAssignment, RegistrationDocument, AttendanceRecord, AuditLog, MedicalForm
)


# ── Subject ──

class SubjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Subject
        fields = ['subject_id', 'code', 'name', 'created_at']
        read_only_fields = ['subject_id', 'created_at']


# ── ExamCenter ──

class ExamCenterSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExamCenter
        fields = ['center_id', 'name', 'address', 'created_at']
        read_only_fields = ['center_id', 'created_at']


# ── Hall ──

class HallSerializer(serializers.ModelSerializer):
    center_name = serializers.CharField(source='center.name', read_only=True)

    class Meta:
        model = Hall
        fields = ['hall_id', 'center', 'center_name', 'name', 'rows', 'columns', 'total_capacity', 'created_at']
        read_only_fields = ['hall_id', 'created_at']


# ── Student (existing) ──

class StudentSerializer(serializers.ModelSerializer):
    subjects = SubjectSerializer(many=True, read_only=True)
    subject_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)

    class Meta:
        model = Student
        fields = [
            'student_id', 'registration_no', 'full_name',
            'date_of_birth', 'gender', 'college_name',
            'email', 'phone', 'consent_signed',
            'status', 'email_verified', 'phone_verified',
            'special_needs', 'special_needs_notes',
            'subjects', 'subject_ids',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['student_id', 'created_at', 'updated_at', 'status', 'email_verified', 'phone_verified']

    def update(self, instance, validated_data):
        subject_ids = validated_data.pop('subject_ids', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if subject_ids is not None:
            subjects = Subject.objects.filter(subject_id__in=subject_ids)
            instance.subjects.set(subjects)
        instance.save()
        return instance


# ── Phase 1: Registration ──

class RegistrationSerializer(serializers.ModelSerializer):
    photo = serializers.ImageField(required=False)
    fingerprint_image = serializers.ImageField(required=False)
    subject_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)

    class Meta:
        model = Student
        fields = [
            'registration_no', 'full_name', 'date_of_birth',
            'gender', 'college_name', 'email', 'phone',
            'photo', 'fingerprint_image', 'consent_signed',
            'special_needs', 'special_needs_notes',
            'subject_ids',
        ]

    def create(self, validated_data):
        subject_ids = validated_data.pop('subject_ids', [])
        fingerprint_image = validated_data.pop('fingerprint_image', None)
        photo = validated_data.pop('photo', None)

        if fingerprint_image:
            validated_data['fingerprint_image'] = fingerprint_image.read()

        student = Student.objects.create(**validated_data)
        if subject_ids:
            subjects = Subject.objects.filter(subject_id__in=subject_ids)
            student.subjects.set(subjects)
        return student


class RegistrationDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = RegistrationDocument
        fields = ['doc_id', 'student_id', 'document_type', 'file_data', 'file_name', 'file_size',
                  'verification_status', 'verification_notes', 'uploaded_at']
        read_only_fields = ['doc_id', 'verification_status', 'verification_notes', 'uploaded_at', 'file_size']

    def validate_file_data(self, value):
        if len(value) > 5 * 1024 * 1024:
            raise serializers.ValidationError("File exceeds 5MB limit")
        return value


class StudentStatusSerializer(serializers.ModelSerializer):
    subjects = SubjectSerializer(many=True, read_only=True)

    class Meta:
        model = Student
        fields = ['student_id', 'registration_no', 'full_name', 'status',
                  'email_verified', 'phone_verified', 'subjects', 'created_at', 'updated_at']


# ── Phase 1: Admin Approval ──

class AdminRegistrationListSerializer(serializers.ModelSerializer):
    subjects = SubjectSerializer(many=True, read_only=True)
    document_count = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = ['student_id', 'registration_no', 'full_name', 'email', 'phone',
                  'college_name', 'status', 'special_needs', 'subjects',
                  'document_count', 'created_at', 'updated_at']

    def get_document_count(self, obj):
        return obj.documents.count()


class AdminApprovalSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['approve', 'reject', 'request_reupload'])
    reason = serializers.CharField(required=False, allow_blank=True)
    document_type = serializers.CharField(required=False, allow_blank=True)


# ── Phase 2: Exam ──

class ExamSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    subject_code = serializers.CharField(source='subject.code', read_only=True)
    center_name = serializers.CharField(source='center.name', read_only=True)
    hall_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    enrolled_ids = serializers.ListField(child=serializers.IntegerField(), write_only=True, required=False)
    halls_detail = HallSerializer(source='halls', many=True, read_only=True)
    enrolled_students_detail = StudentSerializer(source='enrolled_students', many=True, read_only=True)

    class Meta:
        model = Exam
        fields = [
            'exam_id', 'subject', 'subject_name', 'subject_code',
            'date', 'start_time', 'duration_minutes',
            'center', 'center_name',
            'halls', 'hall_ids', 'halls_detail',
            'enrolled_students', 'enrolled_ids', 'enrolled_students_detail',
            'cutoff_date', 'is_locked', 'created_at',
        ]
        read_only_fields = ['exam_id', 'created_at', 'is_locked']

    def validate(self, data):
        if data.get('cutoff_date') and data.get('date'):
            from datetime import datetime, date
            cutoff = data['cutoff_date']
            if cutoff.date() < date.today():
                raise serializers.ValidationError("Cutoff date cannot be in the past")
        return data

    def create(self, validated_data):
        hall_ids = validated_data.pop('hall_ids', [])
        enrolled_ids = validated_data.pop('enrolled_ids', [])
        exam = Exam.objects.create(**validated_data)
        if hall_ids:
            exam.halls.set(Hall.objects.filter(hall_id__in=hall_ids))
        if enrolled_ids:
            exam.enrolled_students.set(Student.objects.filter(student_id__in=enrolled_ids,
                                                              status=Student.RegistrationStatus.APPROVED))
        return exam

    def update(self, instance, validated_data):
        if instance.is_locked:
            raise serializers.ValidationError("Cannot edit a locked exam")
        hall_ids = validated_data.pop('hall_ids', None)
        enrolled_ids = validated_data.pop('enrolled_ids', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if hall_ids is not None:
            instance.halls.set(Hall.objects.filter(hall_id__in=hall_ids))
        if enrolled_ids is not None:
            instance.enrolled_students.set(Student.objects.filter(student_id__in=enrolled_ids,
                                                                   status=Student.RegistrationStatus.APPROVED))
        instance.save()
        return instance


class ExamListSerializer(serializers.ModelSerializer):
    subject_name = serializers.CharField(source='subject.name', read_only=True)
    center_name = serializers.CharField(source='center.name', read_only=True)
    enrolled_count = serializers.SerializerMethodField()
    hall_count = serializers.SerializerMethodField()

    class Meta:
        model = Exam
        fields = ['exam_id', 'subject_name', 'subject_id', 'center_name', 'center_id',
                  'date', 'start_time', 'duration_minutes', 'is_locked',
                  'enrolled_count', 'hall_count', 'created_at']

    def get_enrolled_count(self, obj):
        return obj.enrolled_students.count()

    def get_hall_count(self, obj):
        return obj.halls.count()


# ── Phase 2: SeatAssignment ──

class SeatAssignmentSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.full_name', read_only=True)
    registration_no = serializers.CharField(source='student.registration_no', read_only=True)
    hall_name = serializers.CharField(source='hall.name', read_only=True)
    subject_name = serializers.SerializerMethodField()

    class Meta:
        model = SeatAssignment
        fields = ['assignment_id', 'student_id', 'student_name', 'registration_no',
                  'exam_id', 'hall_id', 'hall_name', 'row', 'col', 'seat_label',
                  'subject_name', 'created_at']

    def get_subject_name(self, obj):
        return obj.exam.subject.name if obj.exam else ''


class SeatMapTriggerSerializer(serializers.Serializer):
    exam_id = serializers.IntegerField()
    reserve_buffer = serializers.BooleanField(default=True)
    alternate_spacing = serializers.BooleanField(default=False)
    gender_grouping = serializers.BooleanField(default=False)


# ── Phase 2: Conflict Check ──

class ScheduleConflictSerializer(serializers.Serializer):
    exam_id = serializers.IntegerField(read_only=True)
    subject = serializers.CharField(read_only=True)
    date = serializers.DateField(read_only=True)
    start_time = serializers.TimeField(read_only=True)
    student_name = serializers.CharField(read_only=True)
    student_id = serializers.IntegerField(read_only=True)


# ── Phase 3: Attendance Record ──

class AttendanceRecordSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.full_name', read_only=True)
    registration_no = serializers.CharField(source='student.registration_no', read_only=True)
    exam_subject = serializers.CharField(source='exam.subject.name', read_only=True)
    hall_name = serializers.CharField(source='hall.name', read_only=True)

    class Meta:
        model = AttendanceRecord
        fields = ['record_id', 'student_id', 'student_name', 'registration_no',
                  'exam_id', 'exam_subject', 'hall_id', 'hall_name',
                  'entry_state', 'entry_time', 'method', 'match_score', 'notes', 'verified_by']


# ── Phase 3: Analytics ──

class AttendanceSummarySerializer(serializers.Serializer):
    total_students = serializers.IntegerField()
    present = serializers.IntegerField()
    absent = serializers.IntegerField()
    fallback = serializers.IntegerField()
    attendance_rate = serializers.FloatField()


class HallOccupancySerializer(serializers.Serializer):
    hall_name = serializers.CharField()
    capacity = serializers.IntegerField()
    assigned = serializers.IntegerField()
    present = serializers.IntegerField()
    utilisation = serializers.FloatField()


# ── Existing serializers (kept for backward compat) ──

class StudentCreateSerializer(serializers.ModelSerializer):
    photo = serializers.ImageField(required=False)
    fingerprint_image = serializers.ImageField(write_only=True, required=False)

    class Meta:
        model = Student
        fields = [
            'registration_no', 'full_name', 'date_of_birth',
            'gender', 'college_name', 'email', 'phone',
            'photo', 'fingerprint_image', 'consent_signed',
        ]


class MedicalFormSerializer(serializers.ModelSerializer):
    class Meta:
        model = MedicalForm
        fields = ['form_id', 'student_id', 'uploaded_at']
        read_only_fields = ['form_id', 'uploaded_at']


class MedicalFormUploadSerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    form_pdf = serializers.FileField()


class FingerprintUploadSerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    finger_type = serializers.ChoiceField(
        choices=['left_thumb', 'left_index', 'left_middle', 'left_ring', 'left_pinky',
                 'right_thumb', 'right_index', 'right_middle', 'right_ring', 'right_pinky'],
        default='right_index'
    )
    fingerprint_image = serializers.ImageField()


class SensorCaptureSerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    finger_type = serializers.ChoiceField(
        choices=['left_thumb', 'left_index', 'left_middle', 'left_ring', 'left_pinky',
                 'right_thumb', 'right_index', 'right_middle', 'right_ring', 'right_pinky'],
        default='right_index'
    )
    fingerprint_image = serializers.ImageField(required=False)
    fingerprint_base64 = serializers.CharField(required=False)

    def validate(self, data):
        if not data.get('fingerprint_image') and not data.get('fingerprint_base64'):
            raise serializers.ValidationError(
                "Either 'fingerprint_image' or 'fingerprint_base64' must be provided."
            )
        return data


class MatchRequestSerializer(serializers.Serializer):
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
    match_found = serializers.BooleanField()
    score = serializers.FloatField()
    interpretation = serializers.CharField()
    method = serializers.CharField()
    student_id = serializers.IntegerField(allow_null=True)
    registration_no = serializers.CharField(allow_null=True)
    full_name = serializers.CharField(allow_null=True)


class QualityResponseSerializer(serializers.Serializer):
    blur_score = serializers.FloatField()
    contrast_score = serializers.FloatField()
    edge_density = serializers.FloatField()
    overall_score = serializers.FloatField()
    is_acceptable = serializers.BooleanField()
