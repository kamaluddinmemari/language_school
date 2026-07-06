from django.db import models
from django.utils import timezone
from accounts.models import ClassRequest, User
import jdatetime


class ClassSession(models.Model):
    """
    جلسه‌ی مجزا از یک کلاس (خصوصی/جبرانی/سایر) که ممکنه بیش از یک جلسه داشته باشه.
    برای هر کلاس، به تعداد session_count ردیف ساخته می‌شه و تاریخ/ساعت اتمام هر جلسه
    جدا از بقیه ثبت و همیشه توسط استاد یا مدیر قابل ویرایش است.
    """
    class_request = models.ForeignKey(ClassRequest, on_delete=models.CASCADE, related_name='sessions')
    session_number = models.PositiveIntegerField()
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['session_number']
        unique_together = ('class_request', 'session_number')

    @property
    def completed_at_jalali(self):
        if not self.completed_at:
            return None
        local_dt = timezone.localtime(self.completed_at)
        return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')

    def __str__(self):
        return f"جلسه {self.session_number} - {self.class_request}"


def ensure_sessions(class_request):
    """ردیف‌های جلسه‌ی موجود نشده رو تا session_count می‌سازه و کوئری‌ست مرتب‌شده رو برمی‌گردونه"""
    existing = set(class_request.sessions.values_list('session_number', flat=True))
    to_create = [
        ClassSession(class_request=class_request, session_number=n)
        for n in range(1, class_request.session_count + 1) if n not in existing
    ]
    if to_create:
        ClassSession.objects.bulk_create(to_create)
    return class_request.sessions.order_by('session_number')
