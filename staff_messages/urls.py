from django.urls import path
from .views import (
    TeacherNoticeListView,
    TeacherNoticeSendView,
    TeacherNoticeDetailView,
    TeacherNoticeMarkAllSeenView,
    TeacherNoticeAcknowledgeView,
    EntryExitRequestListView,
    EntryExitRequestDetailView,
    EntryExitRequestDecideView,
    EntryExitRequestMarkSeenView,
)

urlpatterns = [
    path('teacher-notices/', TeacherNoticeListView.as_view(), name='teacher_notice_list'),
    path('teacher-notices/send/', TeacherNoticeSendView.as_view(), name='teacher_notice_send'),
    path('teacher-notices/mark-all-seen/', TeacherNoticeMarkAllSeenView.as_view(), name='teacher_notice_mark_all_seen'),
    path('teacher-notices/<int:pk>/', TeacherNoticeDetailView.as_view(), name='teacher_notice_detail'),
    path('teacher-notices/<int:pk>/acknowledge/', TeacherNoticeAcknowledgeView.as_view(), name='teacher_notice_acknowledge'),

    path('entry-exit-requests/', EntryExitRequestListView.as_view(), name='entry_exit_request_list'),
    path('entry-exit-requests/mark-seen/', EntryExitRequestMarkSeenView.as_view(), name='entry_exit_request_mark_seen'),
    path('entry-exit-requests/<int:pk>/', EntryExitRequestDetailView.as_view(), name='entry_exit_request_detail'),
    path('entry-exit-requests/<int:pk>/decide/', EntryExitRequestDecideView.as_view(), name='entry_exit_request_decide'),
]
