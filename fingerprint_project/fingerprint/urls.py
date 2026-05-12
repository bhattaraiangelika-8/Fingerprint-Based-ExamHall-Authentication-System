"""
Fingerprint App URL Configuration
"""
from django.urls import path
from . import views
from . import views_registration as reg
from . import views_exam as exam
from . import views_reports as reports

app_name = 'fingerprint'

urlpatterns = [
    # ── Health ──
    path('health/', views.health_check, name='health-check'),

    # ── Existing Fingerprint Endpoints ──
    path('fingerprint/upload/', views.fingerprint_upload, name='fingerprint-upload'),
    path('fingerprint/sensor-capture/', views.sensor_capture, name='sensor-capture'),
    path('fingerprint/match/', views.fingerprint_match, name='fingerprint-match'),

    # ── Existing Student CRUD ──
    path('students/', views.StudentListCreateView.as_view(), name='student-list'),
    path('students/<int:student_id>/', views.StudentDetailView.as_view(), name='student-detail'),

    # ── Existing Medical Forms ──
    path('medical-forms/', views.medical_form_upload, name='medical-form-upload'),

    # ════════════════════════════════════════════
    # Phase 1: Student Registration Portal
    # ════════════════════════════════════════════
    path('register/', reg.student_register, name='student-register'),
    path('register/<int:student_id>/upload-document/', reg.upload_document, name='upload-document'),
    path('register/<int:student_id>/status/', reg.student_status, name='student-status'),

    # Phase 1: Admin Approval
    path('admin/registrations/', reg.admin_registration_list, name='admin-registration-list'),
    path('admin/registrations/<int:student_id>/approve/', reg.admin_approve_student, name='admin-approve'),
    path('admin/registrations/<int:student_id>/reject/', reg.admin_reject_student, name='admin-reject'),
    path('admin/registrations/<int:student_id>/request-reupload/', reg.admin_request_reupload, name='admin-request-reupload'),
    path('admin/registrations/bulk-approve/', reg.admin_bulk_approve, name='admin-bulk-approve'),

    # ════════════════════════════════════════════
    # Phase 2: Subject CRUD
    # ════════════════════════════════════════════
    path('subjects/', exam.SubjectListCreateView.as_view(), name='subject-list'),
    path('subjects/<int:subject_id>/', exam.SubjectDetailView.as_view(), name='subject-detail'),

    # Phase 2: ExamCenter CRUD
    path('centers/', exam.ExamCenterListCreateView.as_view(), name='center-list'),
    path('centers/<int:center_id>/', exam.ExamCenterDetailView.as_view(), name='center-detail'),

    # Phase 2: Hall CRUD
    path('halls/', exam.HallListCreateView.as_view(), name='hall-list'),
    path('halls/<int:hall_id>/', exam.HallDetailView.as_view(), name='hall-detail'),

    # Phase 2: Exam Scheduling
    path('exams/', exam.ExamListCreateView.as_view(), name='exam-list'),
    path('exams/<int:exam_id>/', exam.ExamDetailView.as_view(), name='exam-detail'),
    path('exams/<int:exam_id>/lock/', exam.lock_exam, name='exam-lock'),
    path('exams/conflicts/', exam.check_scheduling_conflicts, name='exam-conflicts'),

    # Phase 2: Seat Auto-Mapping
    path('exams/generate-seat-map/', exam.generate_seat_map_view, name='generate-seat-map'),
    path('exams/<int:exam_id>/seat-assignments/', exam.get_seat_assignments, name='seat-assignments'),

    # ════════════════════════════════════════════
    # Phase 3: Reports
    # ════════════════════════════════════════════
    path('reports/exams/<int:exam_id>/attendance/', reports.attendance_by_exam, name='attendance-by-exam'),
    path('reports/centers/<int:center_id>/attendance/', reports.attendance_by_center, name='attendance-by-center'),
    path('reports/exams/<int:exam_id>/absentees/', reports.absentee_list, name='absentee-list'),
    path('reports/fallback/', reports.fallback_report, name='fallback-report'),
    path('reports/overrides/', reports.override_report, name='override-report'),

    # Phase 3: Analytics
    path('analytics/attendance-rate/', reports.attendance_rate, name='attendance-rate'),
    path('analytics/hall-occupancy/', reports.hall_occupancy, name='hall-occupancy'),
    path('analytics/fallback-rate/', reports.fallback_rate_by_center, name='fallback-rate'),
    path('analytics/peak-entry-times/', reports.peak_entry_times, name='peak-entry-times'),
]
