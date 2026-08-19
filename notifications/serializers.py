from rest_framework import serializers
from .models import Notification, ContactFeedback
from accounts.models import User


class NotificationSerializer(serializers.ModelSerializer):

    class Meta:
        model = Notification
        fields = [
            'id', 'sender', 'recipients', 'title',
            'body', 'notif_type', 'is_read', 'created_at'
        ]
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
        fields = [
            'id', 'sender', 'sender_name', 'sender_role', 'subject', 'message', 'created_at', 'created_at_jalali',
            'admin_reply', 'replied_by', 'replied_by_name', 'replied_at', 'replied_at_jalali', 'seen_by_admin',
        ]
        read_only_fields = ['id', 'sender', 'created_at', 'replied_by', 'replied_at']

    def get_sender_name(self, obj):
        return obj.sender.get_full_name()

    def get_replied_by_name(self, obj):
        return obj.replied_by.get_full_name() if obj.replied_by else None


class ContactFeedbackCreateSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=150, required=False, allow_blank=True)
    message = serializers.CharField()


class ContactFeedbackReplySerializer(serializers.Serializer):
    admin_reply = serializers.CharField()