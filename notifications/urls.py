from django.urls import path
from .views import (
    NotificationListView,
    SendNotificationView,
    MarkAsReadView,
    ContactFeedbackCreateView, MyContactFeedbackListView,
    AdminContactFeedbackListView, AdminContactFeedbackDetailView, MarkContactFeedbackSeenView,
    WebPushPublicKeyView, WebPushSubscribeView, WebPushUnsubscribeView,
)

urlpatterns = [
    path('notifications/', NotificationListView.as_view(), name='notification_list'),
    path('notifications/send/', SendNotificationView.as_view(), name='send_notification'),
    path('notifications/<int:pk>/read/', MarkAsReadView.as_view(), name='mark_as_read'),

    path('feedback/', ContactFeedbackCreateView.as_view(), name='feedback_create'),
    path('feedback/mine/', MyContactFeedbackListView.as_view(), name='feedback_mine'),
    path('feedback/admin/', AdminContactFeedbackListView.as_view(), name='feedback_admin_list'),
    path('feedback/admin/<int:pk>/', AdminContactFeedbackDetailView.as_view(), name='feedback_admin_detail'),
    path('feedback/admin/<int:pk>/seen/', MarkContactFeedbackSeenView.as_view(), name='feedback_admin_seen'),

    path('web-push/public-key/', WebPushPublicKeyView.as_view(), name='web_push_public_key'),
    path('web-push/subscribe/', WebPushSubscribeView.as_view(), name='web_push_subscribe'),
    path('web-push/unsubscribe/', WebPushUnsubscribeView.as_view(), name='web_push_unsubscribe'),
]