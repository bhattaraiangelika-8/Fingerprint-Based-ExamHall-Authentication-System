from django.db import models


class Student(models.Model):
    """Student model with fingerprint enrollment data."""

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
    consent_signed = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'students'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.registration_no} - {self.full_name}"


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
