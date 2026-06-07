from rest_framework import serializers
from .models import Notification
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