from django.urls import path
from .views import (
    RegisterView,
    ForgotPasswordView,
    ResetPasswordView,
    UserProfileView,
    TeacherListCreateView,
    TeacherDetailView,
    PriceSettingView
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot_password'),
    path('reset-password/', ResetPasswordView.as_view(), name='reset_password'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('teachers/', TeacherListCreateView.as_view(), name='teacher_list'),
    path('teachers/<int:pk>/', TeacherDetailView.as_view(), name='teacher_detail'),
    path('price-settings/', PriceSettingView.as_view(), name='price_settings'),
]