from django.contrib import admin
from .models import Student, Subject, ExamCenter, Hall, Exam, SeatAssignment, RegistrationDocument, AttendanceRecord, AuditLog, MedicalForm, ExamSession


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ['student_id', 'registration_no', 'full_name', 'college_name', 'status', 'consent_signed', 'created_at']
    list_filter = ['status', 'gender', 'college_name', 'special_needs']
    search_fields = ['registration_no', 'full_name', 'email']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ['subject_id', 'code', 'name']
    search_fields = ['code', 'name']


@admin.register(ExamCenter)
class ExamCenterAdmin(admin.ModelAdmin):
    list_display = ['center_id', 'name', 'address']
    search_fields = ['name']


@admin.register(Hall)
class HallAdmin(admin.ModelAdmin):
    list_display = ['hall_id', 'name', 'center', 'rows', 'columns', 'total_capacity']
    list_filter = ['center']


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ['exam_id', 'subject', 'date', 'start_time', 'center', 'is_locked']
    list_filter = ['is_locked', 'date', 'center']
    search_fields = ['subject__name', 'subject__code']


@admin.register(SeatAssignment)
class SeatAssignmentAdmin(admin.ModelAdmin):
    list_display = ['assignment_id', 'student', 'exam', 'hall', 'seat_label']
    list_filter = ['exam', 'hall']


@admin.register(RegistrationDocument)
class RegistrationDocumentAdmin(admin.ModelAdmin):
    list_display = ['doc_id', 'student', 'document_type', 'verification_status', 'uploaded_at']
    list_filter = ['document_type', 'verification_status']


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ['record_id', 'student', 'exam', 'entry_state', 'entry_time', 'method']
    list_filter = ['entry_state', 'exam', 'method']


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ['log_id', 'user', 'action', 'timestamp']
    list_filter = ['action', 'timestamp']
    readonly_fields = ['log_id', 'user', 'action', 'target_type', 'target_id', 'details', 'notes', 'ip_address', 'timestamp']


@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = ['session_id', 'exam', 'started_by', 'started_at', 'ended_at', 'is_active']
    list_filter = ['is_active', 'started_at']

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MedicalForm)
class MedicalFormAdmin(admin.ModelAdmin):
    list_display = ['form_id', 'student', 'uploaded_at']
    list_filter = ['uploaded_at']
    search_fields = ['student__full_name', 'student__registration_no']
