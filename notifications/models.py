from django.db import models
from accounts.models import User


class Notification(models.Model):

    class NotifType(models.TextChoices):
        CLASS_APPROVED = 'class_approved', 'کلاس تایید شد'
        CLASS_ACCEPTED = 'class_accepted', 'کلاس پذیرفته شد'
        CLASS_REJECTED = 'class_rejected', 'کلاس رد شد'
        GENERAL = 'general', 'عمومی'

    sender = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_notifications'
    )
    recipients = models.ManyToManyField(
        User,
        related_name='notifications'
    )
    title = models.CharField(max_length=100)
    body = models.TextField()
    notif_type = models.CharField(
        max_length=20,
        choices=NotifType.choices,
        default=NotifType.GENERAL
    )
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.notif_type})"


class ContactFeedback(models.Model):
    """
    خواسته‌ی ۱۶: «تماس با ما» و ثبت نظرات از اپ — هر کاربر (دانش‌آموز/استاد/...) می‌تواند
    پیامی برای مدیریت بفرستد. در پنل ادمین، بخش مجزای «نظرات و پیشنهادات» همه‌ی این پیام‌ها
    را با نام فرستنده و تاریخ/ساعت نشان می‌دهد و امکان پاسخ‌گویی، ویرایش پاسخ، و حذف پیام را
    به مدیر می‌دهد. پاسخ مدیر در همان صفحه‌ی اپ به کاربر نمایش داده می‌شود.
    """
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contact_feedbacks')
    subject = models.CharField(max_length=150, blank=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    admin_reply = models.TextField(blank=True)
    replied_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    replied_at = models.DateTimeField(null=True, blank=True)
    seen_by_admin = models.BooleanField(default=False, help_text='برای نمایش نشان «جدید» در پنل ادمین تا وقتی مدیر بازش نکرده')

    class Meta:
        ordering = ['-created_at']

    @property
    def created_at_jalali(self):
        import jdatetime
        from django.utils import timezone as _tz
        return jdatetime.datetime.fromgregorian(datetime=_tz.localtime(self.created_at)).strftime('%Y/%m/%d - %H:%M')

    @property
    def replied_at_jalali(self):
        if not self.replied_at:
            return None
        import jdatetime
        from django.utils import timezone as _tz
        return jdatetime.datetime.fromgregorian(datetime=_tz.localtime(self.replied_at)).strftime('%Y/%m/%d - %H:%M')

    def __str__(self):
        return f"{self.sender.get_full_name()} — {self.subject or self.message[:30]}"


class WebPushSubscription(models.Model):
    """
    اشتراک Web Push مرورگر ادمین/اداری — برای نمایش ناتیو صدادار سیستم‌عامل (ویندوز/مک) حتی
    وقتی پنل بسته است. هر مرورگر/دستگاه یک اشتراک جدا دارد (یک کاربر می‌تواند چند دستگاه داشته باشد).
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='web_push_subscriptions')
    endpoint = models.URLField(max_length=500, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=200)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"اشتراک push {self.user} — {self.endpoint[:40]}..."
