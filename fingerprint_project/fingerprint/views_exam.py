"""
Exam Scheduling + Seat Auto-Mapping Views (Phase 2)
"""
import logging
from datetime import datetime, date
from rest_framework import status, generics
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Subject, ExamCenter, Hall, Exam, SeatAssignment, Student, AuditLog
from .serializers import (
    SubjectSerializer, ExamCenterSerializer, HallSerializer,
    ExamSerializer, ExamListSerializer, SeatAssignmentSerializer,
    SeatMapTriggerSerializer, ScheduleConflictSerializer,
)
from .seat_mapping.algorithm import generate_seat_map
from .seat_mapping.data_structures import StudentInfo, HallInfo

logger = logging.getLogger('fingerprint')


# ──────────────────────────────────────────────
# Subject CRUD
# ──────────────────────────────────────────────

class SubjectListCreateView(generics.ListCreateAPIView):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer

    def perform_create(self, serializer):
        subject = serializer.save()
        logger.info("Subject created: id=%s, code=%s", subject.subject_id, subject.code)


class SubjectDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    lookup_field = 'subject_id'


# ──────────────────────────────────────────────
# ExamCenter CRUD
# ──────────────────────────────────────────────

class ExamCenterListCreateView(generics.ListCreateAPIView):
    queryset = ExamCenter.objects.all()
    serializer_class = ExamCenterSerializer


class ExamCenterDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ExamCenter.objects.all()
    serializer_class = ExamCenterSerializer
    lookup_field = 'center_id'


# ──────────────────────────────────────────────
# Hall CRUD
# ──────────────────────────────────────────────

class HallListCreateView(generics.ListCreateAPIView):
    queryset = Hall.objects.all()
    serializer_class = HallSerializer
    filterset_fields = ['center']


class HallDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Hall.objects.all()
    serializer_class = HallSerializer
    lookup_field = 'hall_id'


# ──────────────────────────────────────────────
# Exam CRUD
# ──────────────────────────────────────────────

class ExamListCreateView(generics.ListCreateAPIView):
    """GET /api/exams/ — List exams; POST /api/exams/ — Create exam."""

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return ExamListSerializer
        return ExamSerializer

    def get_queryset(self):
        qs = Exam.objects.all().select_related('subject', 'center')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        subject_id = self.request.query_params.get('subject_id')
        center_id = self.request.query_params.get('center_id')
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        if subject_id:
            qs = qs.filter(subject_id=subject_id)
        if center_id:
            qs = qs.filter(center_id=center_id)
        return qs


class ExamDetailView(generics.RetrieveUpdateDestroyAPIView):
    queryset = Exam.objects.all()
    serializer_class = ExamSerializer
    lookup_field = 'exam_id'


@api_view(['POST'])
def lock_exam(request, exam_id):
    """POST /api/exams/<exam_id>/lock/ — Lock exam scheduling."""
    try:
        exam = Exam.objects.get(exam_id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)
    exam.is_locked = True
    exam.save()
    return Response({'message': 'Exam locked', 'exam_id': exam_id})


@api_view(['GET'])
def check_scheduling_conflicts(request):
    """GET /api/exams/conflicts/ — Check for student scheduling conflicts."""
    conflicts = []
    exams = Exam.objects.filter(date__gte=date.today()).select_related('subject')

    from collections import defaultdict
    student_exams = defaultdict(list)
    for exam in exams:
        for student in exam.enrolled_students.all():
            student_exams[student.student_id].append(exam)

    for sid, student_exam_list in student_exams.items():
        sorted_exams = sorted(student_exam_list, key=lambda e: (e.date, e.start_time))
        for i in range(len(sorted_exams) - 1):
            e1 = sorted_exams[i]
            e2 = sorted_exams[i + 1]
            if e1.date == e2.date:
                from datetime import datetime as dt, timedelta
                e1_end = (dt.combine(e1.date, e1.start_time) + timedelta(minutes=e1.duration_minutes)).time()
                if e2.start_time < e1_end:
                    student = Student.objects.get(student_id=sid)
                    conflicts.append({
                        'student_id': sid,
                        'student_name': student.full_name,
                        'exam_id_1': e1.exam_id,
                        'exam_id_2': e2.exam_id,
                        'subject_1': e1.subject.name,
                        'subject_2': e2.subject.name,
                        'date': e1.date,
                        'start_time_1': str(e1.start_time),
                        'start_time_2': str(e2.start_time),
                    })

    return Response({'conflicts': conflicts, 'count': len(conflicts)})


# ──────────────────────────────────────────────
# Seat Auto-Mapping
# ──────────────────────────────────────────────

@api_view(['POST'])
def generate_seat_map_view(request):
    """POST /api/exams/generate-seat-map/ — Auto-assign seats."""
    serializer = SeatMapTriggerSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    exam_id = serializer.validated_data['exam_id']
    try:
        exam = Exam.objects.get(exam_id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)

    if exam.is_locked:
        return Response({'error': 'Exam is locked. Cannot modify seat assignments.'},
                        status=status.HTTP_400_BAD_REQUEST)

    # Clear existing assignments for this exam
    SeatAssignment.objects.filter(exam=exam).delete()

    students = exam.enrolled_students.filter(status=Student.RegistrationStatus.APPROVED)
    halls = list(exam.halls.all())

    if not halls:
        return Response({'error': 'No halls assigned to this exam'}, status=status.HTTP_400_BAD_REQUEST)

    total_capacity = sum(h.total_capacity for h in halls)
    if students.count() > total_capacity:
        return Response({
            'error': f'Not enough seats. {students.count()} students but only {total_capacity} seats available.',
            'students_count': students.count(),
            'total_capacity': total_capacity,
        }, status=status.HTTP_400_BAD_REQUEST)

    constraints = {
        'no_same_subject_neighbours': True,
        'alternate_spacing': serializer.validated_data.get('alternate_spacing', False),
        'gender_grouping': serializer.validated_data.get('gender_grouping', False),
        'reserve_buffer': serializer.validated_data.get('reserve_buffer', True),
    }

    # Convert to data structures
    student_infos = [
        StudentInfo(id=s.student_id, name=s.full_name, roll_number=s.registration_no,
                    subject_code=list(s.subjects.all())[0].code if s.subjects.exists() else '',
                    special_needs=s.special_needs, gender=s.gender)
        for s in students
    ]
    hall_infos = [
        HallInfo(id=h.hall_id, name=h.name, center_id=h.center_id,
                 rows=h.rows, columns=h.columns, total_capacity=h.total_capacity)
        for h in halls
    ]

    try:
        seat_map = generate_seat_map(student_infos, hall_infos, constraints)
    except Exception as e:
        logger.error("Seat map generation failed: %s", e)
        return Response({'error': f'Seat map generation failed: {str(e)}'},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Persist assignments
    assignments_created = 0
    for hall_id, assignments in seat_map['assignments'].items():
        for assignment in assignments:
            SeatAssignment.objects.create(
                student_id=assignment['student_id'],
                exam=exam,
                hall_id=hall_id,
                row=assignment.get('row'),
                col=assignment.get('col'),
                seat_label=assignment.get('seat_label', ''),
            )
            assignments_created += 1

    AuditLog.objects.create(
        user=request.user.username if request.user.is_authenticated else 'system',
        action=AuditLog.ActionType.SEAT_MAP,
        target_type='Exam',
        target_id=exam_id,
        details={'assignments_created': assignments_created, 'halls': len(seat_map['assignments'])},
    )

    response_data = {
        'message': f'Seat map generated for {assignments_created} students',
        'exam_id': exam_id,
        'assignments_created': assignments_created,
        'halls': [],
    }
    for hall_id, h_assignments in seat_map['assignments'].items():
        try:
            hall = Hall.objects.get(hall_id=hall_id)
            response_data['halls'].append({
                'hall_id': hall_id,
                'hall_name': hall.name,
                'assigned': len(h_assignments),
            })
        except Hall.DoesNotExist:
            pass

    if seat_map.get('warnings'):
        response_data['warnings'] = seat_map['warnings']

    return Response(response_data)


@api_view(['GET'])
def get_seat_assignments(request, exam_id):
    """GET /api/exams/<exam_id>/seat-assignments/ — View seat map for an exam."""
    try:
        exam = Exam.objects.get(exam_id=exam_id)
    except Exam.DoesNotExist:
        return Response({'error': 'Exam not found'}, status=status.HTTP_404_NOT_FOUND)

    hall_id = request.query_params.get('hall_id')
    halls_qs = exam.halls.all()
    if hall_id:
        halls_qs = halls_qs.filter(hall_id=hall_id)

    hall_data = []
    for hall in halls_qs:
        assignments = SeatAssignment.objects.filter(exam=exam, hall=hall).select_related('student')
        hall_data.append({
            'hall_id': hall.hall_id,
            'name': hall.name,
            'rows': hall.rows,
            'columns': hall.columns,
            'total_capacity': hall.total_capacity,
            'assignments': [
                {
                    'student_id': a.student_id,
                    'student_name': a.student.full_name,
                    'registration_no': a.student.registration_no,
                    'row': a.row,
                    'col': a.col,
                    'seat_label': a.seat_label,
                }
                for a in assignments
            ],
        })

    return Response({
        'exam_id': exam_id,
        'subject': exam.subject.name,
        'date': exam.date,
        'start_time': exam.start_time,
        'halls': hall_data,
    })
