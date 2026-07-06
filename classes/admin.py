from django.contrib import admin
from .models import ClassSession


@admin.register(ClassSession)
class ClassSessionAdmin(admin.ModelAdmin):
    list_display = ('class_request', 'session_number', 'completed_at', 'completed_by')
    list_filter = ('completed_at',)
