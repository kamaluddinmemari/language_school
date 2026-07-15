from django.contrib import admin
from .models import ClassSlot


@admin.register(ClassSlot)
class ClassSlotAdmin(admin.ModelAdmin):
    list_display = ('number', 'day_type', 'time_slot', 'is_rotating_majority', 'student_status', 'teacher_name', 'capacity', 'assigned_level', 'current_count')
    list_filter = ('day_type', 'student_status', 'is_rotating_majority')
