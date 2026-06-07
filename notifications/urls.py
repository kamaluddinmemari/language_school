from django.urls import path
from .views import (
    NotificationListView,
    SendNotificationView,
    MarkAsReadView
)

urlpatterns = [
    path('notifications/', NotificationListView.as_view(), name='notification_list'),
    path('notifications/send/', SendNotificationView.as_view(), name='send_notification'),
    path('notifications/<int:pk>/read/', MarkAsReadView.as_view(), name='mark_as_read'),
]