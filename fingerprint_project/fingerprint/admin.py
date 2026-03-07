from django.contrib import admin
from .models import Student, MedicalForm


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = [
        'student_id', 'registration_no', 'full_name',
        'college_name', 'consent_signed', 'created_at',
    ]
    list_filter = ['gender', 'college_name', 'consent_signed']
    search_fields = ['registration_no', 'full_name', 'email']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(MedicalForm)
class MedicalFormAdmin(admin.ModelAdmin):
    list_display = ['form_id', 'student', 'uploaded_at']
    list_filter = ['uploaded_at']
    search_fields = ['student__full_name', 'student__registration_no']
