from django.db import models


class Subject(models.Model):
    """Subjects students can enroll in."""

    subject_id = models.AutoField(primary_key=True)
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=150)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'subjects'
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"


class Student(models.Model):
    """Student model with fingerprint enrollment data."""

    class RegistrationStatus(models.TextChoices):
        SUBMITTED = 'SUBMITTED', 'Submitted'
        UNDER_REVIEW = 'UNDER_REVIEW', 'Under Review'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        REUPLOAD_REQUESTED = 'REUPLOAD_REQUESTED', 'Re-upload Requested'

    student_id = models.AutoField(primary_key=True)
    registration_no = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=150)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, blank=True)
    college_name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(max_length=150, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    photo = models.BinaryField(null=True, blank=True)
    fingerprint_template = models.BinaryField(max_length=4096)
    fingerprint_hash = models.CharField(max_length=64)
    fingerprint_image = models.BinaryField(max_length=262144, null=True, blank=True)
    consent_signed = models.BooleanField(default=True)

    # Registration status tracking
    status = models.CharField(
        max_length=30,
        choices=RegistrationStatus.choices,
        default=RegistrationStatus.SUBMITTED,
    )
    email_verified = models.BooleanField(default=False)
    phone_verified = models.BooleanField(default=False)
    special_needs = models.BooleanField(default=False)
    special_needs_notes = models.TextField(blank=True)
    subjects = models.ManyToManyField(
        Subject,
        related_name='students',
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'students'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.registration_no} - {self.full_name}"


class RegistrationDocument(models.Model):
    """Documents uploaded by students during registration."""

    class DocumentType(models.TextChoices):
        GOVT_ID = 'GOVT_ID', 'Government ID'
        PASSPORT_PHOTO = 'PASSPORT_PHOTO', 'Passport Photo'
        FINGERPRINT = 'FINGERPRINT', 'Fingerprint Image'
        OTHER = 'OTHER', 'Other'

    class VerificationStatus(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        VERIFIED = 'VERIFIED', 'Verified'
        REJECTED = 'REJECTED', 'Rejected'

    doc_id = models.AutoField(primary_key=True)
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='documents',
        db_column='student_id',
    )
    document_type = models.CharField(
        max_length=30,
        choices=DocumentType.choices,
        default=DocumentType.GOVT_ID,
    )
    file_data = models.BinaryField()
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveIntegerField(null=True, blank=True)
    verification_status = models.CharField(
        max_length=30,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )
    verification_notes = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'registration_documents'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.document_type} for {self.student.full_name}"


class ExamCenter(models.Model):
    """Physical exam centers with multiple halls."""

    center_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=150)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'exam_centers'
        ordering = ['name']

    def __str__(self):
        return self.name


class Hall(models.Model):
    """Individual exam hall within a center."""

    hall_id = models.AutoField(primary_key=True)
    center = models.ForeignKey(
        ExamCenter,
        on_delete=models.CASCADE,
        related_name='halls',
        db_column='center_id',
    )
    name = models.CharField(max_length=50)
    rows = models.PositiveIntegerField(default=10)
    columns = models.PositiveIntegerField(default=10)
    total_capacity = models.PositiveIntegerField(default=100)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'halls'
        ordering = ['center', 'name']

    def __str__(self):
        return f"{self.center.name} - {self.name}"


class Exam(models.Model):
    """An exam session with subjects, date/time, and assigned halls."""

    exam_id = models.AutoField(primary_key=True)
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='exams',
        db_column='subject_id',
    )
    date = models.DateField()
    start_time = models.TimeField()
    duration_minutes = models.PositiveIntegerField(default=180)
    center = models.ForeignKey(
        ExamCenter,
        on_delete=models.CASCADE,
        related_name='exams',
        db_column='center_id',
    )
    halls = models.ManyToManyField(
        Hall,
        related_name='exams',
        blank=True,
    )
    enrolled_students = models.ManyToManyField(
        Student,
        related_name='exams',
        blank=True,
    )
    cutoff_date = models.DateTimeField(null=True, blank=True)
    is_locked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'exams'
        ordering = ['-date', 'start_time']

    def __str__(self):
        return f"{self.subject.name} ({self.date})"


class SeatAssignment(models.Model):
    """Assigned seat for a student in a specific exam."""

    assignment_id = models.AutoField(primary_key=True)
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='seat_assignments',
        db_column='student_id',
    )
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        related_name='seat_assignments',
        db_column='exam_id',
    )
    hall = models.ForeignKey(
        Hall,
        on_delete=models.CASCADE,
        related_name='seat_assignments',
        db_column='hall_id',
        null=True,
        blank=True,
    )
    row = models.PositiveIntegerField(null=True, blank=True)
    col = models.PositiveIntegerField(null=True, blank=True)
    seat_label = models.CharField(max_length=10, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'seat_assignments'
        ordering = ['exam', 'hall', 'row', 'col']
        unique_together = ['student', 'exam']

    def __str__(self):
        return f"{self.student.full_name} -> {self.exam} [{self.seat_label}]"


class MedicalForm(models.Model):
    """Medical form PDF uploads linked to students."""

    form_id = models.AutoField(primary_key=True)
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='medical_forms',
        db_column='student_id',
    )
    form_pdf = models.BinaryField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'medical_forms'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"Medical Form #{self.form_id} for {self.student.full_name}"


class AttendanceRecord(models.Model):
    """Tracks exam-day entry for a student."""

    class EntryState(models.TextChoices):
        GRANTED = 'GRANTED', 'Granted'
        WRONG_HALL = 'WRONG_HALL', 'Wrong Hall'
        ALREADY_ENTERED = 'ALREADY_ENTERED', 'Already Entered'
        MATCH_FAILED = 'MATCH_FAILED', 'Match Failed'
        FALLBACK_GRANTED = 'FALLBACK_GRANTED', 'Fallback Granted'
        DENIED = 'DENIED', 'Denied'

    record_id = models.AutoField(primary_key=True)
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='attendance_records',
        db_column='student_id',
    )
    exam = models.ForeignKey(
        Exam,
        on_delete=models.CASCADE,
        related_name='attendance_records',
        db_column='exam_id',
    )
    hall = models.ForeignKey(
        Hall,
        on_delete=models.SET_NULL,
        related_name='attendance_records',
        db_column='hall_id',
        null=True, blank=True,
    )
    entry_state = models.CharField(
        max_length=30,
        choices=EntryState.choices,
        default=EntryState.GRANTED,
    )
    entry_time = models.DateTimeField(auto_now_add=True)
    method = models.CharField(max_length=50, blank=True, default='fingerprint')
    match_score = models.FloatField(null=True, blank=True)
    notes = models.TextField(blank=True)
    verified_by = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = 'attendance_records'
        ordering = ['-entry_time']

    def __str__(self):
        return f"{self.student.full_name} - {self.entry_state} @ {self.entry_time}"


class AuditLog(models.Model):
    """Immutable audit trail for admin actions."""

    class ActionType(models.TextChoices):
        APPROVE = 'APPROVE', 'Registration Approved'
        REJECT = 'REJECT', 'Registration Rejected'
        REUPLOAD = 'REUPLOAD', 'Re-upload Requested'
        BULK_APPROVE = 'BULK_APPROVE', 'Bulk Approve'
        OVERRIDE = 'OVERRIDE', 'Entry Override'
        FALLBACK = 'FALLBACK', 'Fallback Auth Used'
        ALERT = 'ALERT', 'Security Alert'
        SEAT_MAP = 'SEAT_MAP', 'Seat Map Generated'
        OTHER = 'OTHER', 'Other'

    log_id = models.AutoField(primary_key=True)
    user = models.CharField(max_length=150)
    user_role = models.CharField(max_length=50, blank=True)
    action = models.CharField(
        max_length=30,
        choices=ActionType.choices,
        default=ActionType.OTHER,
    )
    target_type = models.CharField(max_length=50, blank=True)
    target_id = models.IntegerField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_logs'
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.action} by {self.user} @ {self.timestamp}"

