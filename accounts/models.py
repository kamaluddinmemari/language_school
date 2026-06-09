from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator


class User(AbstractUser):

    class Role(models.TextChoices):
        ADMIN = 'admin', 'مدیر'
        TEACHER = 'teacher', 'معلم'
        STUDENT = 'student', 'دانش‌آموز'

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)
    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=11)
    phone2 = models.CharField(max_length=11, blank=True)
    national_code = models.CharField(max_length=10)
    birth_date = models.DateField(null=True, blank=True)
    language_level = models.CharField(max_length=50, blank=True)
    teacher_level = models.CharField(max_length=50, blank=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)

    def str(self):
        return f"{self.get_full_name()} ({self.role})"

    @property
    def average_rating(self):
        from django.db.models import Avg
        result = self.assigned_classes.filter(is_completed=True, satisfaction__isnull=False).aggregate(Avg('satisfaction'))
        return round(result['satisfaction__avg'] or 0, 1)


class PriceSetting(models.Model):
    one_hour_price = models.PositiveIntegerField(default=400000)
    one_half_hour_price = models.PositiveIntegerField(default=550000)
    teacher_share_percent = models.PositiveIntegerField(default=70)
    school_share_percent = models.PositiveIntegerField(default=30)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    def str(self):
        return f"تنظیمات قیمت (آپدیت: {self.updated_at})"


class ClassRequest(models.Model):

    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار تایید'
        APPROVED = 'approved', 'تایید شده'
        REJECTED = 'rejected', 'رد شده'
        COMPLETED = 'completed', 'مختومه'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'unpaid', 'پرداخت نشده'
        PAID = 'paid', 'پرداخت شده'
        PENDING = 'pending', 'در انتظار تایید'

    class SessionDuration(models.TextChoices):
        ONE_HOUR = '1', 'یک ساعت'
        ONE_HALF = '1.5', 'یک و نیم ساعت'

    class ClassType(models.TextChoices):
        PRIVATE = 'private', 'خصوصی'
        MAKEUP = 'makeup', 'جبرانی'

    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='requests', limit_choices_to={'role': 'student'})
    teacher = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_classes', limit_choices_to={'role': 'teacher'})
    assigned_teachers = models.ManyToManyField(User, blank=True, related_name='referred_classes', limit_choices_to={'role': 'teacher'})
    class_type = models.CharField(max_length=10, choices=ClassType.choices, default=ClassType.PRIVATE)
    language_level = models.CharField(max_length=50)
    proposed_time = models.CharField(max_length=100)
    class_date = models.DateTimeField(null=True, blank=True)
    class_date_approved = models.BooleanField(default=False)
    session_duration = models.CharField(max_length=5, choices=SessionDuration.choices, default=SessionDuration.ONE_HOUR)
    session_count = models.PositiveIntegerField(default=1)
    total_price = models.PositiveIntegerField(default=0)
    teacher_share = models.PositiveIntegerField(default=0)
    school_share = models.PositiveIntegerField(default=0)
    receipt = models.ImageField(upload_to='receipts/', null=True, blank=True)
    amount = models.PositiveIntegerField(default=0)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    satisfaction = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    satisfaction_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, kwargs):
        if self.class_type == 'makeup':
            self.total_price = 0
            self.teacher_share = 0
            self.school_share = 0
        else:
            try:
                price_setting = PriceSetting.objects.latest('updated_at')
            except PriceSetting.DoesNotExist:
                price_setting = None
            if self.session_duration == '1':
                price_per_session = price_setting.one_hour_price if price_setting else 400000
            else:
                price_per_session = price_setting.one_half_hour_price if price_setting else 550000
            teacher_percent = price_setting.teacher_share_percent if price_setting else 70
            school_percent = price_setting.school_share_percent if price_setting else 30
            self.total_price = price_per_session * self.session_count
            self.teacher_share = int(self.total_price * teacher_percent / 100)
            self.school_share = int(self.total_price * school_percent / 100)
        super().save(*args, kwargs)

    def str(self):
        return f"{self.student} - {self.language_level} ({self.status})"


class OTPCode(models.Model):

    class Purpose(models.TextChoices):
        RESET_PASSWORD = 'reset', 'فراموشی رمز'

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otp_codes')
    code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=10, choices=Purpose.choices, default=Purpose.RESET_PASSWORD)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def str(self):
        return f"{self.user} - {self.code} ({self.purpose})"