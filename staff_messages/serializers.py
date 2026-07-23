from rest_framework import serializers
from accounts.models import User
from .models import TeacherNotice, EntryExitPermissionRequest


class TeacherInfoSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'first_name', 'last_name', 'phone']


class TeacherNoticeSerializer(serializers.ModelSerializer):
    teacher_info = TeacherInfoSerializer(source='teacher', read_only=True)
    sender_info = TeacherInfoSerializer(source='sender', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    seen_at_jalali = serializers.ReadOnlyField()
    seen = serializers.ReadOnlyField()

    class Meta:
        model = TeacherNotice
        fields = [
            'id', 'teacher', 'teacher_info', 'sender_info', 'body',
            'created_at', 'created_at_jalali', 'updated_at',
            'seen', 'seen_at', 'seen_at_jalali',
        ]
        read_only_fields = ['created_at', 'updated_at', 'seen_at']


class TeacherNoticeCreateSerializer(serializers.Serializer):
    """ارسال یک پیام به هم‌زمان چند استاد — برای هرکدام یک ردیف TeacherNotice مجزا ساخته می‌شود"""
    teacher_ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)
    body = serializers.CharField(allow_blank=False)

    def validate_teacher_ids(self, value):
        qs = User.objects.filter(id__in=value, role__in=User.TEACHER_LIKE_ROLES)
        if qs.count() != len(set(value)):
            raise serializers.ValidationError('یک یا چند استاد انتخاب‌شده معتبر نیست')
        return value


class EntryExitPermissionRequestSerializer(serializers.ModelSerializer):
    teacher_info = TeacherInfoSerializer(source='teacher', read_only=True)
    decided_by_info = TeacherInfoSerializer(source='decided_by', read_only=True)
    created_at_jalali = serializers.ReadOnlyField()
    decided_at_jalali = serializers.ReadOnlyField()
    teacher_seen_at_jalali = serializers.ReadOnlyField()
    permission_type_display = serializers.CharField(source='get_permission_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = EntryExitPermissionRequest
        fields = [
            'id', 'teacher', 'teacher_info', 'student_name', 'class_level',
            'permission_type', 'permission_type_display', 'request_message',
            'status', 'status_display', 'response_message',
            'coordination_person', 'coordination_phone',
            'decided_by', 'decided_by_info', 'decided_at', 'decided_at_jalali',
            'teacher_seen_at', 'teacher_seen_at_jalali',
            'created_at', 'created_at_jalali', 'updated_at',
        ]
        read_only_fields = ['teacher', 'status', 'response_message', 'coordination_person', 'coordination_phone', 'decided_by', 'decided_at', 'teacher_seen_at', 'created_at', 'updated_at']
