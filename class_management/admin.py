from django.contrib import admin
from .models import ClassSlot, TermHoliday


@admin.register(ClassSlot)
class ClassSlotAdmin(admin.ModelAdmin):
    list_display = ('number', 'day_type', 'time_slot', 'teacher_name', 'capacity', 'assigned_level', 'current_count')
    list_filter = ('day_type',)


@admin.register(TermHoliday)
class TermHolidayAdmin(admin.ModelAdmin):
    list_display = ('term', 'date', 'date_jalali', 'description')
    list_filter = ('term',)
