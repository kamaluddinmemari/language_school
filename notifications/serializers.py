from rest_framework import serializers
from django.db import models
from .models import Notification, ContactFeedback, DailyTask, DailyTaskCompletion, DailyTaskReply
from accounts.models import User

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'sender', 'recipients', 'title', 'body', 'notif_type', 'is_read', 'created_at']
        read_only_fields = ['sender', 'created_at']

class SendNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['recipients', 'title', 'body', 'notif_type']

class ContactFeedbackSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    sender_role = serializers.CharField(source='sender.role', read_only=True)
    replied_by_name = serializers.SerializerMethodField()
    created_at_jalali = serializers.ReadOnlyField()
    replied_at_jalali = serializers.ReadOnlyField()
    class Meta:
        model = ContactFeedback
        fields = ['id', 'sender', 'sender_name', 'sender_role', 'subject', 'message', 'created_at', 'created_at_jalali', 'admin_reply', 'replied_by', 'replied_by_name', 'replied_at', 'replied_at_jalali', 'seen_by_admin']
        read_only_fields = ['id', 'sender', 'created_at', 'replied_by', 'replied_at']
    def get_sender_name(self, obj): return obj.sender.get_full_name()
    def get_replied_by_name(self, obj): return obj.replied_by.get_full_name() if obj.replied_by else None

class ContactFeedbackCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=150, required=False, allow_blank=True)
    message = serializers.CharField()

class ContactFeedbackReplySerializer(serializers.Serializer):
    admin_reply = serializers.CharField()

class DailyTaskCompletionSerializer(serializers.ModelSerializer):
    completed_at_jalali = serializers.ReadOnlyField()
    employee_name = serializers.SerializerMethodField()
    class Meta:
        model = DailyTaskCompletion
        fields = ['id', 'employee', 'employee_name', 'completed_on', 'note', 'completed_at', 'completed_at_jalali']
        read_only_fields = fields
    def get_employee_name(self, obj): return obj.employee.get_full_name() or obj.employee.username

MANAGER_ROLES = ('admin', 'office', 'evaluator')


class DailyTaskReplySerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    author_role = serializers.CharField(source='author.role', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    parent_preview = serializers.SerializerMethodField()
    mine = serializers.SerializerMethodField()
    attachment_url = serializers.SerializerMethodField()
    edited = serializers.SerializerMethodField()
    class Meta:
        model = DailyTaskReply
        fields = ['id', 'task', 'author', 'author_name', 'author_role', 'parent', 'parent_preview', 'body', 'attachment', 'attachment_url', 'scheduled_at', 'created_on', 'created_at', 'updated_at', 'created_at_jalali', 'mine', 'edited']
        read_only_fields = ['id', 'task', 'author', 'author_name', 'author_role', 'parent_preview', 'attachment_url', 'created_on', 'created_at', 'updated_at', 'created_at_jalali', 'mine', 'edited']
    def get_author_name(self, obj): return obj.author.get_full_name() or obj.author.username
    def get_parent_preview(self, obj):
        if not obj.parent_id: return None
        p = obj.parent
        return {'id': p.id, 'author_name': p.author.get_full_name() or p.author.username, 'body': (p.body or '')[:140]}
    def get_mine(self, obj):
        request = self.context.get('request')
        return bool(request and obj.author_id == request.user.pk)
    def get_attachment_url(self, obj):
        if not obj.attachment:
            return None
        request = self.context.get('request')
        return request.build_absolute_uri(obj.attachment.url) if request else obj.attachment.url
    def get_edited(self, obj):
        return obj.updated_at > obj.created_at


class DailyTaskSerializer(serializers.ModelSerializer):
    replies = serializers.SerializerMethodField()
    repeat_daily = serializers.SerializerMethodField()
    assigned_employee_names = serializers.SerializerMethodField()
    completed = serializers.SerializerMethodField()
    completed_at_jalali = serializers.SerializerMethodField()
    completion_details = serializers.SerializerMethodField()
    assigned_to_me = serializers.SerializerMethodField()
    audience_label = serializers.SerializerMethodField()
    archive_completed_at = serializers.SerializerMethodField()
    archive_completed_by = serializers.SerializerMethodField()
    class Meta:
        model = DailyTask
        fields = ['id', 'title', 'body', 'link_label', 'link_url', 'start_date', 'start_time', 'end_date', 'end_time', 'repeat_daily', 'assigned_to', 'assigned_employee_names', 'audience_mode', 'audience_label', 'is_information', 'show_body_with_title', 'is_active', 'created_at', 'archive_completed_at', 'archive_completed_by', 'completed', 'completed_at_jalali', 'completion_details', 'assigned_to_me', 'replies']
        read_only_fields = ['created_at', 'assigned_employee_names', 'audience_label', 'completed', 'completed_at_jalali', 'completion_details', 'assigned_to_me', 'replies']
    def get_archive_completion(self, obj):
        return obj.completions.select_related('employee').order_by('-completed_at').first()
    def get_archive_completed_at(self, obj):
        completion = self.get_archive_completion(obj)
        return completion.completed_at_jalali if completion else None
    def get_archive_completed_by(self, obj):
        completion = self.get_archive_completion(obj)
        return (completion.employee.get_full_name() or completion.employee.username) if completion else None
    def get_repeat_daily(self, obj):
        from .models import REPEAT_FOREVER_DATE
        return obj.end_date == REPEAT_FOREVER_DATE
    def get_replies(self, obj):
        try:
            return self._replies(obj)
        except Exception:  # اگر جدول پاسخ‌ها هنوز migrate نشده، ثبت و نمایش دستورها نباید خراب شود
            return []
    def _replies(self, obj):
        from django.utils import timezone
        request = self.context['request']
        qs = obj.replies.select_related('author', 'parent', 'parent__author').filter(models.Q(scheduled_at__isnull=True) | models.Q(scheduled_at__lte=timezone.now()))
        if self.get_repeat_daily(obj):
            qs = qs.filter(created_on=timezone.localdate())  # دستور تکراری: هر روز گفتگو از نو
        # دسترسی به خود دستور در view کنترل شده است؛ همه اعضای مجاز گفتگو
        # باید پاسخ‌های همکاران را نیز ببینند تا بتوانند به هر پاسخ ریپلای کنند.
        return DailyTaskReplySerializer(qs, many=True, context=self.context).data
    def get_assigned_employee_names(self, obj):
        return [u.get_full_name() or u.username for u in obj.assigned_to.all()]
    def get_audience_label(self, obj):
        names = self.get_assigned_employee_names(obj)
        recipient = 'همه' if not names else '، '.join(names)
        return f"{'محرمانه' if obj.audience_mode == 'confidential' else 'عادی'} — دریافت‌کننده: {recipient}"
    def get_assigned_to_me(self, obj):
        # بدون ارجاع = عمومی (برای همه)؛ وگرنه فقط اگر نام کاربر در فهرست ارجاع باشد
        assigned = list(obj.assigned_to.all())
        return not assigned or any(u.pk == self.context['request'].user.pk for u in assigned)
    def get_completed(self, obj):
        from django.utils import timezone
        return obj.completions.filter(employee=self.context['request'].user, completed_on=timezone.localdate()).exists()
    def get_completed_at_jalali(self, obj):
        from django.utils import timezone
        completion = obj.completions.filter(employee=self.context['request'].user, completed_on=timezone.localdate()).first()
        return completion.completed_at_jalali if completion else None
    def get_completion_details(self, obj):
        from django.utils import timezone
        request = self.context['request']
        qs = obj.completions.filter(completed_on=timezone.localdate()).select_related('employee')
        if request.user.role not in ('admin', 'office', 'evaluator'):
            qs = qs.filter(employee=request.user)
        return DailyTaskCompletionSerializer(qs, many=True).data

class DailyTaskStaffSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    class Meta:
        model = User
        fields = ['id', 'name', 'role']
    def get_name(self, obj): return obj.get_full_name() or obj.username
