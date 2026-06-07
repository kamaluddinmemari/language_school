from django.urls import path
from .views import (
    ClassRequestListCreateView,
    ClassRequestDetailView,
    ApproveClassView,
    TeacherAcceptView
)

urlpatterns = [
    path('classes/', ClassRequestListCreateView.as_view(), name='class_list'),
    path('classes/<int:pk>/', ClassRequestDetailView.as_view(), name='class_detail'),
    path('classes/<int:pk>/approve/', ApproveClassView.as_view(), name='class_approve'),
    path('classes/<int:pk>/accept/', TeacherAcceptView.as_view(), name='class_accept'),
]