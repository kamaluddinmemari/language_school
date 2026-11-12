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
    class Meta:
        model = DailyTaskReply
        fields = ['id', 'task', 'author', 'author_name', 'author_role', 'parent', 'parent_preview', 'body', 'created_on', 'created_at', 'created_at_jalali', 'mine']
        read_only_fields = fields
    def get_author_name(self, obj): return obj.author.get_full_name() or obj.author.username
    def get_parent_preview(self, obj):
        if not obj.parent_id: return None
        p = obj.parent
        return {'id': p.id, 'author_name': p.author.get_full_name() or p.author.username, 'body': (p.body or '')[:140]}
    def get_mine(self, obj):
        request = self.context.get('request')
        return bool(request and obj.author_id == request.user.pk)


class DailyTaskSerializer(serializers.ModelSerializer):
    replies = serializers.SerializerMethodField()
    repeat_daily = serializers.SerializerMethodField()
    assigned_employee_names = serializers.SerializerMethodField()
    completed = serializers.SerializerMethodField()
    completed_at_jalali = serializers.SerializerMethodField()
    completion_details = serializers.SerializerMethodField()
    assigned_to_me = serializers.SerializerMethodField()
    class Meta:
        model = DailyTask
        fields = ['id', 'title', 'body', 'link_label', 'link_url', 'start_date', 'start_time', 'end_date', 'end_time', 'repeat_daily', 'assigned_to', 'assigned_employee_names', 'is_active', 'created_at', 'completed', 'completed_at_jalali', 'completion_details', 'assigned_to_me', 'replies']
        read_only_fields = ['created_at', 'assigned_employee_names', 'completed', 'completed_at_jalali', 'completion_details', 'assigned_to_me', 'replies']
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
        qs = obj.replies.select_related('author', 'parent', 'parent__author')
        if self.get_repeat_daily(obj):
            qs = qs.filter(created_on=timezone.localdate())  # دستور تکراری: هر روز گفتگو از نو
        if request.user.role not in MANAGER_ROLES:
            qs = qs.filter(models.Q(author=request.user) | models.Q(author__role__in=MANAGER_ROLES))
        return DailyTaskReplySerializer(qs, many=True, context=self.context).data
    def get_assigned_employee_names(self, obj):
        return [u.get_full_name() or u.username for u in obj.assigned_to.all()]
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
