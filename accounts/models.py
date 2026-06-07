from django.db import models
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):

    class Role(models.TextChoices):
        ADMIN = 'admin', 'مدیر'
        TEACHER = 'teacher', 'معلم'
        STUDENT = 'student', 'دانش‌آموز'

    role = models.CharField(
        max_length=10,
        choices=Role.choices,
        default=Role.STUDENT
    )
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=11)
    phone2 = models.CharField(max_length=11, blank=True)
    national_code = models.CharField(max_length=10)
    birth_date = models.DateField(null=True, blank=True)
    language_level = models.CharField(max_length=50, blank=True)
    avatar = models.ImageField(
        upload_to='avatars/',
        null=True,
        blank=True
    )

    def str(self):
        return f"{self.get_full_name()} ({self.role})"


class ClassRequest(models.Model):

    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار تایید'
        APPROVED = 'approved', 'تایید شده'
        REJECTED = 'rejected', 'رد شده'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'unpaid', 'پرداخت نشده'
        PAID = 'paid', 'پرداخت شده'
        PENDING = 'pending', 'در انتظار تایید'

    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='requests',
        limit_choices_to={'role': 'student'}
    )
    teacher = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_classes',
        limit_choices_to={'role': 'teacher'}
    )
    language_level = models.CharField(max_length=50)
    proposed_time = models.CharField(max_length=100)
    receipt = models.ImageField(
        upload_to='receipts/',
        null=True,
        blank=True
    )
    amount = models.PositiveIntegerField(default=0)
    payment_status = models.CharField(
        max_length=10,
        choices=PaymentStatus.choices,
        default=PaymentStatus.UNPAID
    )
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.PENDING
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def str(self):
        return f"{self.student} - {self.language_level} ({self.status})"


class OTPCode(models.Model):

    class Purpose(models.TextChoices):
        RESET_PASSWORD = 'reset', 'فراموشی رمز'

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='otp_codes'
    )
    code = models.CharField(max_length=6)
    purpose = models.CharField(
        max_length=10,
        choices=Purpose.choices,
        default=Purpose.RESET_PASSWORD
    )
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def str(self):
        return f"{self.user} - {self.code} ({self.purpose})"