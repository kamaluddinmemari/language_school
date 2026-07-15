from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.utils import timezone
import jdatetime
from .validators import username_validator

persian_only_validator = RegexValidator(
    regex=r'^[\u0600-\u06FF\s\u200C]+$',
    message='این فیلد فقط باید با حروف فارسی نوشته شود (نه انگلیسی یا اعداد لاتین).'
)


class User(AbstractUser):

    class Role(models.TextChoices):
        ADMIN = 'admin', 'مدیر'
        TEACHER = 'teacher', 'معلم'
        STUDENT = 'student', 'دانش‌آموز'
        EVALUATOR = 'evaluator', 'مدیر آموزش'

    # نقش‌هایی که باید مثل استاد در لیست اساتید دیده بشن و بتونن کلاس بگیرن/تدریس کنن.
    # مدیر آموزش هم استاد محسوب می‌شه (اشتراکی، یک‌طرفه) — عکسش صادق نیست، یک استاد ساده مدیر آموزش نیست.
    TEACHER_LIKE_ROLES = ['teacher', 'evaluator']

    # override می‌کنیم چون AbstractUser پیش‌فرض یونیکد (شامل حروف فارسی) رو قبول می‌کنه؛
    # طبق تصمیم کارفرما، نام کاربری فقط باید حروف/اعداد/کاراکترهای انگلیسی باشد.
    username = models.CharField(max_length=150, unique=True, validators=[username_validator])

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.STUDENT)
    first_name = models.CharField(max_length=150, validators=[persian_only_validator])
    last_name = models.CharField(max_length=150, validators=[persian_only_validator])
    father_name = models.CharField(max_length=150, blank=True, validators=[persian_only_validator])
    phone = models.CharField(max_length=11, unique=True)
    phone2 = models.CharField(max_length=11, blank=True)
    national_code = models.CharField(max_length=10, unique=True, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    language_level = models.CharField(max_length=50, blank=True)
    teacher_level = models.CharField(max_length=50, blank=True)
    avatar = models.ImageField(upload_to='avatars/', null=True, blank=True)

    def __str__(self):
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

    def __str__(self):
        return f"تنظیمات قیمت (آپدیت: {self.updated_at})"


class ClassRequest(models.Model):

    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار تایید'
        REFERRED = 'referred', 'ارجاع‌شده به استاد'
        CONFIRMED = 'confirmed', 'تایید نهایی - منتظر برگزاری'
        COMPLETED = 'completed', 'مختومه'
        REJECTED = 'rejected', 'رد شده'
        CANCELLED = 'cancelled', 'کنسل شده'

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
        OTHER = 'other', 'سایر'

    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='requests', limit_choices_to={'role': 'student'})
    teacher = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_classes', limit_choices_to={'role__in': User.TEACHER_LIKE_ROLES})
    assigned_teachers = models.ManyToManyField(User, blank=True, related_name='referred_classes', limit_choices_to={'role__in': User.TEACHER_LIKE_ROLES})
    accepted_teachers = models.ManyToManyField(User, blank=True, related_name='accepted_classes', limit_choices_to={'role__in': User.TEACHER_LIKE_ROLES})
    class_type = models.CharField(max_length=10, choices=ClassType.choices, default=ClassType.PRIVATE)
    custom_class_type = models.CharField(max_length=100, blank=True)
    language_level = models.CharField(max_length=50)
    proposed_time = models.CharField(max_length=100, blank=True)
    suggested_teacher_name = models.CharField(max_length=150, blank=True)
    class_date = models.DateTimeField(null=True, blank=True)
    class_date_approved = models.BooleanField(default=False)
    session_duration = models.CharField(max_length=5, choices=SessionDuration.choices, default=SessionDuration.ONE_HALF)
    session_count = models.PositiveIntegerField(default=1)
    total_price = models.PositiveIntegerField(default=0)
    teacher_share = models.PositiveIntegerField(default=0)
    school_share = models.PositiveIntegerField(default=0)
    teacher_payment_status = models.BooleanField(default=False)
    teacher_payment_date = models.DateTimeField(null=True, blank=True)
    teacher_payment_amount = models.PositiveIntegerField(default=0)
    receipt = models.ImageField(upload_to='receipts/', null=True, blank=True)
    amount = models.PositiveIntegerField(default=0)
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    satisfaction = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    satisfaction_text = models.TextField(blank=True)
    satisfaction_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def created_at_jalali(self):
        """تاریخ و ساعت ثبت به شمسی، برای نمایش در پنل/اپ"""
        if not self.created_at:
            return None
        local_dt = timezone.localtime(self.created_at)
        return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')

    @property
    def completed_at_jalali(self):
        """تاریخ و ساعت اتمام کلاس به شمسی"""
        if not self.completed_at:
            return None
        local_dt = timezone.localtime(self.completed_at)
        return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')

    @property
    def class_date_jalali(self):
        """تاریخ و ساعت برگزاری کلاس به شمسی"""
        if not self.class_date:
            return None
        local_dt = timezone.localtime(self.class_date)
        return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')

    def save(self, *args, **kwargs):
        if self.class_type in ['makeup', 'other']:
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
        super().save(*args, **kwargs)

    def __str__(self):
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

    def __str__(self):
        return f"{self.user} - {self.code} ({self.purpose})"