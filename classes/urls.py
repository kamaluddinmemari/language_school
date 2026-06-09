from django.urls import path
from .views import (
    ClassRequestListCreateView,
    ClassRequestDetailView,
    ApproveClassView,
    RejectClassView,
    TeacherAcceptView,
    CompleteClassView,
    AdminConfirmCompleteView,
    SatisfactionView
)

urlpatterns = [
    path('classes/', ClassRequestListCreateView.as_view(), name='class_list'),
    path('classes/<int:pk>/', ClassRequestDetailView.as_view(), name='class_detail'),
    path('classes/<int:pk>/approve/', ApproveClassView.as_view(), name='class_approve'),
    path('classes/<int:pk>/reject/', RejectClassView.as_view(), name='class_reject'),
    path('classes/<int:pk>/accept/', TeacherAcceptView.as_view(), name='class_accept'),
    path('classes/<int:pk>/complete/', CompleteClassView.as_view(), name='class_complete'),
    path('classes/<int:pk>/confirm/', AdminConfirmCompleteView.as_view(), name='class_confirm'),
    path('classes/<int:pk>/satisfaction/', SatisfactionView.as_view(), name='class_satisfaction'),
]