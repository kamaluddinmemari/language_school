from django.contrib import admin
from .models import GroupSession, GroupSessionParticipant, GroupSessionMeeting, GroupPriceSetting, GroupSessionAttendance


@admin.register(GroupSession)
class GroupSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'session_type', 'title', 'language_level', 'status', 'capacity', 'participant_count', 'teacher')
    list_filter = ('session_type', 'status')


@admin.register(GroupSessionParticipant)
class GroupSessionParticipantAdmin(admin.ModelAdmin):
    list_display = ('group_session', 'student', 'payment_status', 'satisfaction')


@admin.register(GroupSessionMeeting)
class GroupSessionMeetingAdmin(admin.ModelAdmin):
    list_display = ('group_session', 'meeting_number', 'completed_at')


@admin.register(GroupPriceSetting)
class GroupPriceSettingAdmin(admin.ModelAdmin):
    list_display = ('price_for_two', 'price_for_three_plus', 'teacher_share_percent', 'school_share_percent', 'updated_at')


@admin.register(GroupSessionAttendance)
class GroupSessionAttendanceAdmin(admin.ModelAdmin):
    list_display = ('meeting', 'participant', 'status', 'paid', 'updated_at')
    list_filter = ('status', 'paid')
