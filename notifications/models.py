from django.db import models
from django.utils import timezone
from accounts.models import User


class Notification(models.Model):
    class NotifType(models.TextChoices):
        CLASS_APPROVED = 'class_approved', 'کلاس تایید شد'
        CLASS_ACCEPTED = 'class_accepted', 'کلاس پذیرفته شد'
        CLASS_REJECTED = 'class_rejected', 'کلاس رد شد'
        GENERAL = 'general', 'عمومی'
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_notifications')
    recipients = models.ManyToManyField(User, related_name='notifications')
    title = models.CharField(max_length=100)
    body = models.TextField()
    notif_type = models.CharField(max_length=20, choices=NotifType.choices, default=NotifType.GENERAL)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"{self.title} ({self.notif_type})"


class ContactFeedback(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contact_feedbacks')
    subject = models.CharField(max_length=150, blank=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    admin_reply = models.TextField(blank=True)
    replied_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    replied_at = models.DateTimeField(null=True, blank=True)
    seen_by_admin = models.BooleanField(default=False, help_text='برای نمایش نشان جدید تا وقتی مدیر بازش نکرده')
    class Meta:
        ordering = ['-created_at']
    @property
    def created_at_jalali(self):
        import jdatetime
        return jdatetime.datetime.fromgregorian(datetime=timezone.localtime(self.created_at)).strftime('%Y/%m/%d - %H:%M')
    @property
    def replied_at_jalali(self):
        if not self.replied_at:
            return None
        import jdatetime
        return jdatetime.datetime.fromgregorian(datetime=timezone.localtime(self.replied_at)).strftime('%Y/%m/%d - %H:%M')
    def __str__(self):
        return f"{self.sender.get_full_name()} — {self.subject or self.message[:30]}"


class WebPushSubscription(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='web_push_subscriptions')
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=200)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"اشتراک push {self.user} — {self.endpoint[:40]}..."


class DailyTask(models.Model):
    """دستور روزانه یا بازه‌ای برای یک یا همهٔ کارکنان اداری."""
    title = models.CharField(max_length=180)
    body = models.TextField()
    link_label = models.CharField(max_length=80, blank=True, default='اینجا')
    link_url = models.CharField(max_length=300, blank=True, default='')
    start_date = models.DateField(default=timezone.localdate)
    start_time = models.TimeField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    assigned_to = models.ManyToManyField(User, blank=True, related_name='daily_tasks', help_text='خالی = مشترک برای همه کارکنان')
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='created_daily_tasks')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['start_date', 'created_at', 'id']
    def __str__(self):
        return self.title


class DailyTaskCompletion(models.Model):
    task = models.ForeignKey(DailyTask, on_delete=models.CASCADE, related_name='completions')
    employee = models.ForeignKey(User, on_delete=models.CASCADE, related_name='daily_task_completions')
    completed_on = models.DateField(default=timezone.localdate)
    note = models.TextField(blank=True, default='')
    completed_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['task', 'employee', 'completed_on'], name='unique_daily_task_employee_day_completion')]
        ordering = ['-completed_at']
    @property
    def completed_at_jalali(self):
        import jdatetime
        return jdatetime.datetime.fromgregorian(datetime=timezone.localtime(self.completed_at)).strftime('%Y/%m/%d - %H:%M')
