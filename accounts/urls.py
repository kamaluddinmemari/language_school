from django.urls import path
from .views import (
    RegisterView,
    ForgotPasswordView,
    ResetPasswordView,
    UserProfileView,
    TeacherListView
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('forgot-password/', ForgotPasswordView.as_view(), name='forgot_password'),
    path('reset-password/', ResetPasswordView.as_view(), name='reset_password'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('teachers/', TeacherListView.as_view(), name='teacher_list'),
]