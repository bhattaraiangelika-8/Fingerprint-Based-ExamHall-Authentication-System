"""
Registration + Admin Approval Views (Phase 1)
"""
import logging
from rest_framework import status, generics
from rest_framework.decorators import api_view
from rest_framework.response import Response

from django.db import models as dj_models
from .models import Student, RegistrationDocument, AuditLog
from .serializers import (
    RegistrationSerializer, RegistrationDocumentSerializer,
    StudentStatusSerializer, AdminRegistrationListSerializer,
    AdminApprovalSerializer, StudentSerializer,
)

logger = logging.getLogger('fingerprint')


# ──────────────────────────────────────────────
# Student Registration
# ──────────────────────────────────────────────

@api_view(['POST'])
def student_register(request):
    """POST /api/register/ — Self-registration for students."""
    serializer = RegistrationSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    student = serializer.save()
    logger.info("Student registered: id=%s, reg=%s", student.student_id, student.registration_no)

    return Response({
        'message': 'Registration submitted successfully',
        'student_id': student.student_id,
        'status': student.status,
    }, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def upload_document(request, student_id):
    """POST /api/register/<student_id>/upload-document/ — Upload registration document."""
    try:
        student = Student.objects.get(student_id=student_id)
    except Student.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = RegistrationDocumentSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    doc = serializer.save(student=student)
    logger.info("Document uploaded: doc_id=%s, student=%s, type=%s",
                doc.doc_id, student_id, doc.document_type)

    return Response({
        'message': 'Document uploaded successfully',
        'doc_id': doc.doc_id,
        'document_type': doc.document_type,
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def student_status(request, student_id):
    """GET /api/register/<student_id>/status/ — Check registration status."""
    try:
        student = Student.objects.get(student_id=student_id)
    except Student.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

    serializer = StudentStatusSerializer(student)
    return Response(serializer.data)


# ──────────────────────────────────────────────
# Admin Approval Workflow
# ──────────────────────────────────────────────

@api_view(['GET'])
def admin_registration_list(request):
    """GET /api/admin/registrations/ — List registrations (filterable by status)."""
    status_filter = request.query_params.get('status')
    search = request.query_params.get('search')

    queryset = Student.objects.all()
    if status_filter:
        queryset = queryset.filter(status=status_filter.upper())
    if search:
        queryset = queryset.filter(
            dj_models.Q(full_name__icontains=search) |
            dj_models.Q(registration_no__icontains=search) |
            dj_models.Q(email__icontains=search)
        )

    serializer = AdminRegistrationListSerializer(queryset, many=True)
    return Response(serializer.data)


@api_view(['POST'])
def admin_approve_student(request, student_id):
    """POST /api/admin/registrations/<student_id>/approve/"""
    try:
        student = Student.objects.get(student_id=student_id)
    except Student.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

    if student.status != Student.RegistrationStatus.SUBMITTED and student.status != Student.RegistrationStatus.UNDER_REVIEW:
        return Response({'error': f'Cannot approve student with status {student.status}'},
                        status=status.HTTP_400_BAD_REQUEST)

    student.status = Student.RegistrationStatus.APPROVED
    student.save()

    AuditLog.objects.create(
        user=request.user.username if request.user.is_authenticated else 'admin',
        action=AuditLog.ActionType.APPROVE,
        target_type='Student',
        target_id=student.student_id,
        details={'registration_no': student.registration_no},
    )

    logger.info("Student approved: id=%s, reg=%s", student.student_id, student.registration_no)
    return Response({'message': 'Registration approved', 'student_id': student.student_id, 'status': student.status})


@api_view(['POST'])
def admin_reject_student(request, student_id):
    """POST /api/admin/registrations/<student_id>/reject/"""
    try:
        student = Student.objects.get(student_id=student_id)
    except Student.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

    reason = request.data.get('reason', '')
    student.status = Student.RegistrationStatus.REJECTED
    student.save()

    AuditLog.objects.create(
        user=request.user.username if request.user.is_authenticated else 'admin',
        action=AuditLog.ActionType.REJECT,
        target_type='Student',
        target_id=student.student_id,
        details={'registration_no': student.registration_no, 'reason': reason},
    )

    logger.info("Student rejected: id=%s, reg=%s, reason=%s", student.student_id, student.registration_no, reason)
    return Response({'message': 'Registration rejected', 'student_id': student.student_id, 'status': student.status})


@api_view(['POST'])
def admin_request_reupload(request, student_id):
    """POST /api/admin/registrations/<student_id>/request-reupload/"""
    try:
        student = Student.objects.get(student_id=student_id)
    except Student.DoesNotExist:
        return Response({'error': 'Student not found'}, status=status.HTTP_404_NOT_FOUND)

    document_type = request.data.get('document_type', '')
    reason = request.data.get('reason', '')
    student.status = Student.RegistrationStatus.REUPLOAD_REQUESTED
    student.save()

    AuditLog.objects.create(
        user=request.user.username if request.user.is_authenticated else 'admin',
        action=AuditLog.ActionType.REUPLOAD,
        target_type='Student',
        target_id=student.student_id,
        details={'document_type': document_type, 'reason': reason},
    )

    logger.info("Re-upload requested: student=%s, doc=%s", student_id, document_type)
    return Response({'message': 'Re-upload requested', 'student_id': student.student_id, 'status': student.status})


@api_view(['POST'])
def admin_bulk_approve(request):
    """POST /api/admin/registrations/bulk-approve/"""
    student_ids = request.data.get('student_ids', [])
    if not student_ids:
        return Response({'error': 'No student IDs provided'}, status=status.HTTP_400_BAD_REQUEST)

    updated = Student.objects.filter(
        student_id__in=student_ids,
        status__in=[Student.RegistrationStatus.SUBMITTED, Student.RegistrationStatus.UNDER_REVIEW]
    ).update(status=Student.RegistrationStatus.APPROVED)

    for sid in student_ids:
        AuditLog.objects.create(
            user=request.user.username if request.user.is_authenticated else 'admin',
            action=AuditLog.ActionType.BULK_APPROVE,
            target_type='Student',
            target_id=sid,
        )

    logger.info("Bulk approve: %d students approved", updated)
    return Response({'message': f'{updated} students approved', 'count': updated})
