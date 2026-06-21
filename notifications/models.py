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
