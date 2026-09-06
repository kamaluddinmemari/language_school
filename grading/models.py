from django.db import models
from django.conf import settings
from django.utils import timezone
import jdatetime


def _jalali(dt):
    if not dt:
        return None
    local_dt = timezone.localtime(dt)
    return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')


class GradeFieldSetting(models.Model):
    """
    تنظیم عنوان/فعال‌بودن/سهم (از ۱۰۰) هر یک از ۵ فیلد نمره‌ی ترم، به تفکیک رده سنی
    (کودک/نوجوان/بزرگسال) — همان چیزی که در «تنظیم فیلدهای نمره» توسط مدیر آموزش/مدیر
    تعریف می‌شود. سهم هر فیلد آزادانه قابل تغییر است؛ جمع سهم فیلدهای فعال معمولاً باید
    ۱۰۰ باشد ولی این محدودیت به‌صورت سخت‌گیرانه در بک‌اند enforce نمی‌شود (فقط هشدار در پنل).
    """

    class FieldKey(models.TextChoices):
        CP = 'cp', 'CP'
        MIDTERM = 'midterm', 'میان‌ترم'
        WRITING1 = 'writing1', 'رایتینگ ۱'
        WRITING2 = 'writing2', 'رایتینگ ۲'
        FINAL = 'final', 'پایان‌ترم'

    class AgeGroup(models.TextChoices):
        KIDS = 'kids', 'کودک'
        TEEN = 'teen', 'نوجوان'
        ADULT = 'adult', 'بزرگسال'

    age_group = models.CharField(max_length=10, choices=AgeGroup.choices)
    field_key = models.CharField(max_length=20, choices=FieldKey.choices)
    title = models.CharField(max_length=50, help_text='عنوان نمایشی این فیلد برای این رده سنی — قابل ویرایش')
    is_active = models.BooleanField(default=True, help_text='آیا این فیلد برای این رده سنی فعال است')
    max_score = models.PositiveIntegerField(default=0, help_text='سهم این فیلد از نمره‌ی نهایی ۱۰۰ (وقتی فعال است)')
    order = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['age_group', 'order']
        constraints = [
            models.UniqueConstraint(fields=['age_group', 'field_key'], name='unique_grade_field_per_age_group')
        ]

    def __str__(self):
        return f"{self.get_age_group_display()} — {self.title} ({'فعال' if self.is_active else 'غیرفعال'})"


class GradePassingSetting(models.Model):
    """حداقل نمره قبولی (از ۱۰۰) به تفکیک رده سنی."""

    class AgeGroup(models.TextChoices):
        KIDS = 'kids', 'کودک'
        TEEN = 'teen', 'نوجوان'
        ADULT = 'adult', 'بزرگسال'

    age_group = models.CharField(max_length=10, choices=AgeGroup.choices, unique=True)
    passing_score = models.PositiveIntegerField(default=60, help_text='حداقل نمره قبولی از ۱۰۰')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"حداقل قبولی {self.get_age_group_display()}: {self.passing_score}"


FIELD_KEYS = ['cp', 'midterm', 'writing1', 'writing2', 'final']

DEFAULT_FIELD_TITLES = {
    'cp': 'CP',
    'midterm': 'میان‌ترم',
    'writing1': 'رایتینگ ۱',
    'writing2': 'رایتینگ ۲',
    'final': 'پایان‌ترم',
}

DEFAULT_MAX_SCORES = {
    'cp': 10,
    'midterm': 20,
    'writing1': 15,
    'writing2': 15,
    'final': 40,
}


def ensure_default_grade_settings():
    """
    اگر تنظیمات فیلدهای نمره یا حداقل قبولی برای یکی از رده‌های سنی هنوز ساخته نشده،
    با مقادیر پیش‌فرض می‌سازد — طوری که همان بار اول باز کردن «تنظیم فیلدهای نمره»،
    مدیر یک فرم کامل و آماده‌ی ویرایش ببیند، نه صفحه‌ی خالی.
    """
    for age_group, _ in GradeFieldSetting.AgeGroup.choices:
        for order, field_key in enumerate(FIELD_KEYS):
            GradeFieldSetting.objects.get_or_create(
                age_group=age_group, field_key=field_key,
                defaults={
                    'title': DEFAULT_FIELD_TITLES[field_key],
                    'is_active': True,
                    'max_score': DEFAULT_MAX_SCORES[field_key],
                    'order': order,
                },
            )
        GradePassingSetting.objects.get_or_create(
            age_group=age_group, defaults={'passing_score': 60},
        )


class StudentGrade(models.Model):
    """
    نمره‌ی یک دانش‌آموز مشخص در یک کلاس ترمیک مشخص (= یک درس در یک ترم). هر ۵ فیلد نمره
    جداگانه ذخیره می‌شود؛ نمره‌ی کل با جمع فیلدهای فعال (طبق GradeFieldSetting رده سنی
    همان کلاس) محاسبه و در total_score ذخیره می‌شود. بعد از «قطعی کردن» کل کلاس، رکوردهای
    قبول‌شده قفل می‌شوند؛ رکوردهای fail طبق تصمیم کارفرما همچنان توسط ادمین/اداری قابل
    ویرایش می‌مانند (مثلاً برای اصلاح بعد از تجدیدنظر).
    """
    class_slot = models.ForeignKey(
        'class_management.ClassSlot', on_delete=models.CASCADE, related_name='grades',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='grades',
        limit_choices_to={'role': 'student'},
    )
    term = models.ForeignKey(
        'class_management.Term', on_delete=models.SET_NULL, null=True, blank=True, related_name='student_grades',
    )
    level = models.CharField(max_length=50, blank=True, help_text='سطح کلاس در لحظه‌ی ثبت/قطعی‌شدن نمره')
    age_group = models.CharField(max_length=10, blank=True, help_text='رده سنی محاسبه‌شده از روی سطح کلاس')

    cp_score = models.PositiveIntegerField(null=True, blank=True)
    midterm_score = models.PositiveIntegerField(null=True, blank=True)
    writing1_score = models.PositiveIntegerField(null=True, blank=True)
    writing2_score = models.PositiveIntegerField(null=True, blank=True)
    final_score = models.PositiveIntegerField(null=True, blank=True)

    total_score = models.PositiveIntegerField(null=True, blank=True)
    is_finalized = models.BooleanField(default=False)
    is_fail = models.BooleanField(default=False)

    entered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    finalized_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['class_slot', 'student'], name='unique_grade_per_student_per_class')
        ]
        indexes = [
            models.Index(fields=['term', 'student']),
            models.Index(fields=['class_slot', 'is_finalized']),
        ]

    @property
    def score_map(self):
        return {
            'cp': self.cp_score,
            'midterm': self.midterm_score,
            'writing1': self.writing1_score,
            'writing2': self.writing2_score,
            'final': self.final_score,
        }

    @property
    def is_editable(self):
        """قفل فقط برای رکوردهای قبول‌شده‌ی قطعی‌شده معنی دارد؛ رکورد fail همیشه قابل ویرایش می‌ماند."""
        if not self.is_finalized:
            return True
        return self.is_fail

    def refresh_snapshot(self):
        """رده سنی/سطح را از روی کلاس فعلی به‌روز می‌کند — قبل از محاسبه‌ی نمره لازم است."""
        from class_management.models import infer_age_group_from_level
        self.level = self.class_slot.assigned_level or ''
        self.age_group = infer_age_group_from_level(self.level) or ''

    def compute_total(self):
        """جمع نمرات فیلدهای فعال طبق تنظیمات فیلد نمره‌ی رده سنی این رکورد."""
        if not self.age_group:
            self.refresh_snapshot()
        active_keys = set(
            GradeFieldSetting.objects.filter(age_group=self.age_group, is_active=True).values_list('field_key', flat=True)
        ) if self.age_group else set(FIELD_KEYS)
        scores = self.score_map
        total = 0
        for key in FIELD_KEYS:
            if key in active_keys:
                total += scores.get(key) or 0
        return total

    def apply_computation(self):
        self.refresh_snapshot()
        self.total_score = self.compute_total()
        passing = 60
        if self.age_group:
            setting = GradePassingSetting.objects.filter(age_group=self.age_group).first()
            if setting:
                passing = setting.passing_score
        self.is_fail = self.total_score is not None and self.total_score < passing

    @property
    def finalized_at_jalali(self):
        return _jalali(self.finalized_at)

    @property
    def updated_at_jalali(self):
        return _jalali(self.updated_at)

    def __str__(self):
        return f"نمره {self.student.get_full_name()} — کلاس {self.class_slot.number}"
