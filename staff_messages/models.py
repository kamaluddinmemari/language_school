from django.db import models
from django.utils import timezone
from accounts.models import User
import jdatetime


def _jalali(dt):
    if not dt:
        return None
    local_dt = timezone.localtime(dt)
    return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')


class TeacherNotice(models.Model):
    """
    پیام مدیریتی که مدیر برای یک استاد (یا هم‌زمان چند استاد — هر کدام یک ردیف مجزا) می‌فرستد.
    پیش‌فرض برای «یادآوری ثبت غیاب» طراحی شده، ولی متن کاملاً آزاد و قابل‌ویرایش است —
    یعنی هر پیامی می‌تواند از همین‌جا برای استاد فرستاده شود.
    """

    DEFAULT_ATTENDANCE_REMINDER = 'لطفاً حضور و غیاب کلاس خود را ثبت کنید.'

    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_teacher_notices')
    teacher = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='received_teacher_notices',
        limit_choices_to={'role__in': User.TEACHER_LIKE_ROLES}
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    seen_at = models.DateTimeField(null=True, blank=True)

    is_deleted = models.BooleanField(default=False)
    deleted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='deleted_teacher_notices'
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def seen(self):
        return self.seen_at is not None

    @property
    def created_at_jalali(self):
        return _jalali(self.created_at)

    @property
    def seen_at_jalali(self):
        return _jalali(self.seen_at)

    def __str__(self):
        return f"پیام به {self.teacher} — {'دیده‌شده' if self.seen else 'دیده‌نشده'}"


class EntryExitPermissionRequest(models.Model):
    """
    درخواست مجوز ورود/خروج دانش‌آموز که استاد از اپ ثبت می‌کند و مدیر تایید/رد می‌کند.
    """

    class PermissionType(models.TextChoices):
        ENTRY = 'entry', 'مجوز ورود'
        EXIT = 'exit', 'مجوز خروج'

    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار بررسی'
        APPROVED = 'approved', 'تایید شد'
        REJECTED = 'rejected', 'رد شد'

    teacher = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='entry_exit_requests',
        limit_choices_to={'role__in': User.TEACHER_LIKE_ROLES}
    )
    student_name = models.CharField(max_length=150)
    class_level = models.CharField(max_length=50)
    permission_type = models.CharField(max_length=10, choices=PermissionType.choices)
    request_message = models.TextField(blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    response_message = models.TextField(blank=True)
    coordination_person = models.CharField(max_length=150, blank=True, help_text='نام فرد جهت هماهنگی ورود/خروج')
    coordination_phone = models.CharField(max_length=20, blank=True, help_text='شماره تماس جهت هماهنگی ورود/خروج')
    decided_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='decided_entry_exit_requests'
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    # وقتی استاد (مقصدِ ارجاع) وارد صفحه‌ی مربوطه در اپ می‌شود، خودکار همین‌جا سین می‌خورد —
    # مخصوصاً برای مواردی که خودِ مدیر ثبت/ارجاع داده (نه استاد)
    teacher_seen_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    is_deleted = models.BooleanField(default=False)
    deleted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='deleted_entry_exit_requests'
    )
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def created_at_jalali(self):
        return _jalali(self.created_at)

    @property
    def decided_at_jalali(self):
        return _jalali(self.decided_at)

    @property
    def teacher_seen_at_jalali(self):
        return _jalali(self.teacher_seen_at)

    def __str__(self):
        return f"{self.get_permission_type_display()} — {self.student_name} ({self.teacher})"
