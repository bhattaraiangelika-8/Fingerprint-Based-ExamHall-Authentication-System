"""
Fingerprint App URL Configuration
──────────────────────────────────
"""

from django.urls import path
from . import views

app_name = 'fingerprint'

urlpatterns = [
    # Health check
    path('health/', views.health_check, name='health-check'),

    # Fingerprint processing
    path('fingerprint/upload/', views.fingerprint_upload, name='fingerprint-upload'),
    path('fingerprint/sensor-capture/', views.sensor_capture, name='sensor-capture'),
    path('fingerprint/match/', views.fingerprint_match, name='fingerprint-match'),

    # Student CRUD
    path('students/', views.StudentListCreateView.as_view(), name='student-list'),
    path('students/<int:student_id>/', views.StudentDetailView.as_view(), name='student-detail'),

    # Medical forms
    path('medical-forms/', views.medical_form_upload, name='medical-form-upload'),

    # Frontend pages
    path('', views.home_view, name='home'),
    path('enroll/', views.enroll_view, name='enroll'),
    path('enroll/<int:student_id>/fingerprint/', views.fingerprint_upload_view, name='fingerprint_upload'),
    path('enroll/<int:student_id>/medical/', views.medical_upload_view, name='medical_upload'),
    path('verify/', views.verify_view, name='verify'),
    path('student/<int:student_id>/', views.student_detail_view, name='student_detail'),
]
