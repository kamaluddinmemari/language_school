from rest_framework import serializers
from .models import Notification, ContactFeedback, DailyTask, DailyTaskCompletion
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

class DailyTaskSerializer(serializers.ModelSerializer):
    assigned_employee_names = serializers.SerializerMethodField()
    completed = serializers.SerializerMethodField()
    completed_at_jalali = serializers.SerializerMethodField()
    completion_details = serializers.SerializerMethodField()
    assigned_to_me = serializers.SerializerMethodField()
    class Meta:
        model = DailyTask
        fields = ['id', 'title', 'body', 'link_label', 'link_url', 'start_date', 'start_time', 'end_date', 'end_time', 'assigned_to', 'assigned_employee_names', 'is_active', 'created_at', 'completed', 'completed_at_jalali', 'completion_details', 'assigned_to_me']
        read_only_fields = ['created_at', 'assigned_employee_names', 'completed', 'completed_at_jalali', 'completion_details', 'assigned_to_me']
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
