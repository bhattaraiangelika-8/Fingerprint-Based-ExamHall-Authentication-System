"""
Reports + Analytics Views (Phase 3)
"""
import csv
import io
import logging
from datetime import date, datetime, timedelta
from collections import defaultdict

from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Exam, Hall, SeatAssignment, AttendanceRecord, Student, AuditLog
from .serializers import AttendanceRecordSerializer, AttendanceSummarySerializer, HallOccupancySerializer

logger = logging.getLogger('fingerprint')


# ──────────────────────────────────────────────
# 4.1 Attendance Reports
# ──────────────────────────────────────────────

@api_view(['GET'])
def attendance_by_exam(request, exam_id):
    """GET /api/reports/exams/<exam_id>/attendance/ — Per-student attendance for an exam."""
    try:
        exam = Exam.objects.get(exam_id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)

    export = request.query_params.get('export', 'json')
    records = AttendanceRecord.objects.filter(exam=exam).select_related('student', 'hall')

    if export == 'csv':
        return _export_attendance_csv(exam, records, 'exam')

    serializer = AttendanceRecordSerializer(records, many=True)
    return Response({
        'exam_id': exam_id,
        'subject': exam.subject.name,
        'date': exam.date,
        'total_enrolled': exam.enrolled_students.count(),
        'records': serializer.data,
    })


@api_view(['GET'])
def attendance_by_center(request, center_id):
    """GET /api/reports/centers/<center_id>/attendance/ — Attendance for a center."""
    from .models import ExamCenter
    try:
        center = ExamCenter.objects.get(center_id=center_id)
    except ExamCenter.DoesNotExist:
        return Response({'error': 'Center not found'}, status=status.HTTP_404_NOT_FOUND)

    date_from = request.query_params.get('date_from')
    date_to = request.query_params.get('date_to')
    qs = AttendanceRecord.objects.filter(exam__center=center).select_related('student', 'hall', 'exam__subject')
    if date_from:
        qs = qs.filter(exam__date__gte=date_from)
    if date_to:
        qs = qs.filter(exam__date__lte=date_to)

    export = request.query_params.get('export', 'json')
    if export == 'csv':
        return _export_attendance_csv(None, qs, 'center', center.name)

    serializer = AttendanceRecordSerializer(qs, many=True)
    return Response({'center_id': center_id, 'center_name': center.name, 'records': serializer.data})


@api_view(['GET'])
def absentee_list(request, exam_id):
    """GET /api/reports/exams/<exam_id>/absentees/ — Students with no scan and no fallback."""
    try:
        exam = Exam.objects.get(exam_id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)

    enrolled_ids = set(exam.enrolled_students.values_list('student_id', flat=True))
    attended_ids = set(AttendanceRecord.objects.filter(
        exam=exam, entry_state__in=['GRANTED', 'FALLBACK_GRANTED']
    ).values_list('student_id', flat=True))

    absentee_ids = enrolled_ids - attended_ids
    absentees = Student.objects.filter(student_id__in=absentee_ids)

    data = [{
        'student_id': s.student_id,
        'registration_no': s.registration_no,
        'full_name': s.full_name,
        'email': s.email,
        'phone': s.phone,
    } for s in absentees]

    if request.query_params.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="absentees_exam_{exam_id}.csv"'
        writer = csv.writer(response)
        writer.writerow(['student_id', 'registration_no', 'full_name', 'email', 'phone'])
        for row in data:
            writer.writerow([row['student_id'], row['registration_no'], row['full_name'], row['email'], row['phone']])
        return response

    return Response({'exam_id': exam_id, 'absentee_count': len(data), 'absentees': data})


@api_view(['GET'])
def fallback_report(request):
    """GET /api/reports/fallback/ — All non-fingerprint entries with reasons."""
    records = AttendanceRecord.objects.filter(
        entry_state='FALLBACK_GRANTED'
    ).select_related('student', 'exam__subject', 'hall')

    exam_id = request.query_params.get('exam_id')
    if exam_id:
        records = records.filter(exam_id=exam_id)

    serializer = AttendanceRecordSerializer(records, many=True)
    return Response({
        'count': records.count(),
        'records': serializer.data,
    })


@api_view(['GET'])
def override_report(request):
    """GET /api/reports/overrides/ — All admin overrides with reasons."""
    overrides = AuditLog.objects.filter(action=AuditLog.ActionType.OVERRIDE)
    data = [{
        'log_id': o.log_id,
        'user': o.user,
        'action': o.action,
        'target_id': o.target_id,
        'details': o.details,
        'notes': o.notes,
        'timestamp': o.timestamp,
    } for o in overrides]

    return Response({'count': len(data), 'overrides': data})


# ──────────────────────────────────────────────
# 4.2 Analytics Dashboard
# ──────────────────────────────────────────────

@api_view(['GET'])
def attendance_rate(request):
    """GET /api/analytics/attendance-rate/ — Overall attendance rate per exam session."""
    exam_id = request.query_params.get('exam_id')

    exams = Exam.objects.all()
    if exam_id:
        exams = exams.filter(exam_id=exam_id)

    results = []
    for exam in exams:
        total = exam.enrolled_students.count()
        if total == 0:
            continue
        present = AttendanceRecord.objects.filter(
            exam=exam, entry_state__in=['GRANTED', 'FALLBACK_GRANTED']
        ).count()
        fallback = AttendanceRecord.objects.filter(
            exam=exam, entry_state='FALLBACK_GRANTED'
        ).count()
        results.append({
            'exam_id': exam.exam_id,
            'subject': exam.subject.name,
            'date': exam.date,
            'total_students': total,
            'present': present,
            'absent': total - present,
            'fallback': fallback,
            'attendance_rate': round(present / total * 100, 1) if total > 0 else 0.0,
        })

    return Response({'sessions': results, 'count': len(results)})


@api_view(['GET'])
def hall_occupancy(request):
    """GET /api/analytics/hall-occupancy/ — Hall-wise occupancy utilisation."""
    exam_id = request.query_params.get('exam_id')

    halls = Hall.objects.all()
    if exam_id:
        halls = halls.filter(exams__exam_id=exam_id)

    results = []
    for hall in halls:
        assigned = SeatAssignment.objects.filter(hall=hall)
        if exam_id:
            assigned = assigned.filter(exam_id=exam_id)
        assigned_count = assigned.count()
        present = AttendanceRecord.objects.filter(
            hall=hall, entry_state__in=['GRANTED', 'FALLBACK_GRANTED']
        ).count()

        results.append({
            'hall_id': hall.hall_id,
            'hall_name': hall.name,
            'center': hall.center.name,
            'capacity': hall.total_capacity,
            'assigned': assigned_count,
            'present': present,
            'utilisation': round(assigned_count / hall.total_capacity * 100, 1) if hall.total_capacity > 0 else 0.0,
        })

    return Response({'halls': results, 'count': len(results)})


@api_view(['GET'])
def fallback_rate_by_center(request):
    """GET /api/analytics/fallback-rate/ — Fallback auth rate per center."""
    from .models import ExamCenter

    centers = ExamCenter.objects.all()
    results = []
    for center in centers:
        total_entries = AttendanceRecord.objects.filter(exam__center=center).count()
        fallback_entries = AttendanceRecord.objects.filter(
            exam__center=center, entry_state='FALLBACK_GRANTED'
        ).count()
        results.append({
            'center_id': center.center_id,
            'center_name': center.name,
            'total_entries': total_entries,
            'fallback_entries': fallback_entries,
            'fallback_rate': round(fallback_entries / total_entries * 100, 1) if total_entries > 0 else 0.0,
        })

    return Response({'centers': results})


@api_view(['GET'])
def peak_entry_times(request):
    """GET /api/analytics/peak-entry-times/ — Histogram of entry times."""
    exam_id = request.query_params.get('exam_id')

    records = AttendanceRecord.objects.filter(entry_state='GRANTED')
    if exam_id:
        records = records.filter(exam_id=exam_id)

    # Group by hour
    hour_buckets = defaultdict(int)
    for record in records:
        hour = record.entry_time.hour
        hour_buckets[hour] += 1

    histogram = [{'hour': h, 'count': c} for h, c in sorted(hour_buckets.items())]

    return Response({
        'total_entries': records.count(),
        'histogram': histogram,
    })


# ──────────────────────────────────────────────
# CSV Export Helpers
# ──────────────────────────────────────────────

def _export_attendance_csv(exam, records, scope, scope_name=''):
    """Generate CSV response for attendance records."""
    response = HttpResponse(content_type='text/csv')
    filename = f'attendance_{scope}_{scope_name if scope_name else exam.exam_id if exam else "all"}.csv'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(['Student ID', 'Registration No', 'Student Name', 'Subject', 'Hall',
                     'Entry State', 'Entry Time', 'Method', 'Verified By'])

    for r in records.select_related('student', 'hall', 'exam__subject'):
        writer.writerow([
            r.student_id,
            r.student.registration_no,
            r.student.full_name,
            r.exam.subject.name if r.exam else '',
            r.hall.name if r.hall else '',
            r.entry_state,
            r.entry_time.strftime('%Y-%m-%d %H:%M:%S') if r.entry_time else '',
            r.method,
            r.verified_by,
        ])

    return response
