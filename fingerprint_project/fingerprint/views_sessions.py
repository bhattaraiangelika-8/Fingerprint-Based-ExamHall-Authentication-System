"""
Exam Session Views — On-the-day exam session management
"""
import logging
from datetime import datetime

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Exam, ExamSession, SeatAssignment, AttendanceRecord
from .serializers import ExamSessionSerializer, StartSessionSerializer

logger = logging.getLogger('fingerprint')


@api_view(['POST'])
def start_session(request):
    """
    POST /api/exam-sessions/start/

    Start a session for an exam. Auto-ends any other active session.
    Body: { exam_id, started_by }
    """
    serializer = StartSessionSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        exam = Exam.objects.get(exam_id=serializer.validated_data['exam_id'])
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)

    ended_ids = []
    for s in ExamSession.objects.filter(is_active=True, ended_at__isnull=True):
        s.is_active = False
        s.ended_at = datetime.now()
        s.save(update_fields=['is_active', 'ended_at'])
        ended_ids.append(s.session_id)

    session = ExamSession.objects.create(
        exam=exam,
        started_by=serializer.validated_data['started_by'],
    )

    logger.info(
        "Session started: session_id=%s, exam_id=%s, by=%s (auto-ended prior: %s)",
        session.session_id, exam.exam_id, session.started_by, ended_ids or 'none',
    )

    return Response(ExamSessionSerializer(session).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
def end_session(request, session_id):
    """
    POST /api/exam-sessions/<id>/end/

    End an active session.
    """
    try:
        session = ExamSession.objects.get(session_id=session_id, is_active=True)
    except ExamSession.DoesNotExist:
        return Response({'error': 'Active session not found'}, status=status.HTTP_404_NOT_FOUND)

    session.is_active = False
    session.ended_at = datetime.now()
    session.save(update_fields=['is_active', 'ended_at'])

    logger.info("Session ended: session_id=%s", session.session_id)
    return Response(ExamSessionSerializer(session).data)


@api_view(['GET'])
def active_session(request):
    """
    GET /api/exam-sessions/active/

    Get the currently active session (only one globally).
    """
    try:
        session = ExamSession.objects.get(is_active=True, ended_at__isnull=True)
        return Response(ExamSessionSerializer(session).data)
    except ExamSession.DoesNotExist:
        return Response({'session_id': None, 'is_active': False})


@api_view(['GET'])
def list_sessions(request):
    """
    GET /api/exam-sessions/

    List all sessions, filterable by date.
    Query params: ?date=YYYY-MM-DD
    """
    qs = ExamSession.objects.select_related('exam__subject').all()
    date_param = request.query_params.get('date')
    if date_param:
        qs = qs.filter(exam__date=date_param)
    return Response(ExamSessionSerializer(qs, many=True).data)
