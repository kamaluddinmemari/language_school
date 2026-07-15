from django.contrib import admin
from .models import TeacherNotice, EntryExitPermissionRequest


@admin.register(TeacherNotice)
class TeacherNoticeAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'sender', 'seen', 'is_deleted', 'created_at')
    list_filter = ('is_deleted',)


@admin.register(EntryExitPermissionRequest)
class EntryExitPermissionRequestAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'student_name', 'permission_type', 'status', 'is_deleted', 'created_at')
    list_filter = ('permission_type', 'status', 'is_deleted')
