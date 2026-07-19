from rest_framework import serializers
from .models import ClassSlot


class ClassSlotSerializer(serializers.ModelSerializer):
    day_type_display = serializers.ReadOnlyField()
    is_three_day = serializers.ReadOnlyField()
    capacity_status = serializers.ReadOnlyField()
    seats_left = serializers.ReadOnlyField()
    surplus = serializers.ReadOnlyField()
    updated_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = ClassSlot
        fields = [
            'id', 'number', 'title', 'day_type', 'day_type_display',
            'capacity', 'teacher_name', 'time_slot', 'notes', 'is_three_day',
            'assigned_level', 'current_count', 'capacity_status', 'seats_left', 'surplus',
            'updated_at', 'updated_at_jalali',
        ]
        read_only_fields = ['updated_at']


class LevelDemandSerializer(serializers.Serializer):
    level = serializers.CharField()
    count = serializers.IntegerField(min_value=0)
    is_rotating_majority = serializers.BooleanField(default=False)
    student_status = serializers.ChoiceField(
        choices=['', 'rotating', 'only_morning', 'one_day_preference', 'hybrid_online', 'other'],
        required=False, default='', allow_blank=True
    )
    student_status_other = serializers.CharField(required=False, default='', allow_blank=True)


class AllocateClassesSerializer(serializers.Serializer):
    levels = LevelDemandSerializer(many=True)
    tolerance = serializers.IntegerField(min_value=0, default=0)
    thursday_only_count = serializers.IntegerField(min_value=0, default=0)
    friday_only_count = serializers.IntegerField(min_value=0, default=0)


class ConfirmOverflowSerializer(serializers.Serializer):
    level = serializers.CharField()
    count = serializers.IntegerField(min_value=1)
    target_slot_id = serializers.IntegerField()
    # کل باقیمانده‌ی واقعیِ همین سطح که pending_overflow گزارش کرده بود (نه فقط عددی که به
    # کلاس دوم می‌رود) — تا اگر مدیر کمتر از کل باقیمانده را وارد کند، بقیه گم نشوند.
    remaining_count = serializers.IntegerField(min_value=1, required=False)


class TransferSurplusSerializer(serializers.Serializer):
    target_slot_id = serializers.IntegerField(required=False)
    count = serializers.IntegerField(required=False, min_value=1)


class SpinOffSurplusSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=1)
    teacher_name = serializers.CharField(required=False, allow_blank=True, default='')
    number = serializers.IntegerField(required=False)
    day_type = serializers.CharField(required=False, allow_blank=True, default='')
    time_slot = serializers.CharField(required=False, allow_blank=True, default='')
    capacity = serializers.IntegerField(required=False, min_value=1)
