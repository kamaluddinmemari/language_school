from rest_framework import serializers
from .models import ClassSlot


class ClassSlotSerializer(serializers.ModelSerializer):
    day_type_display = serializers.ReadOnlyField()
    student_status_display = serializers.ReadOnlyField()
    is_three_day = serializers.ReadOnlyField()
    is_effectively_rotating = serializers.ReadOnlyField()
    capacity_status = serializers.ReadOnlyField()
    seats_left = serializers.ReadOnlyField()
    updated_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = ClassSlot
        fields = [
            'id', 'number', 'title', 'day_type', 'day_type_display',
            'is_rotating_majority', 'student_status', 'student_status_other', 'student_status_display',
            'capacity', 'teacher_name', 'time_slot', 'is_three_day', 'is_effectively_rotating',
            'assigned_level', 'current_count', 'capacity_status', 'seats_left',
            'updated_at', 'updated_at_jalali',
        ]
        read_only_fields = ['updated_at']


class LevelDemandSerializer(serializers.Serializer):
    level = serializers.CharField()
    count = serializers.IntegerField(min_value=0)


class AllocateClassesSerializer(serializers.Serializer):
    levels = LevelDemandSerializer(many=True)
    tolerance = serializers.IntegerField(min_value=0, default=0)
    thursday_only_count = serializers.IntegerField(min_value=0, default=0)
    friday_only_count = serializers.IntegerField(min_value=0, default=0)
