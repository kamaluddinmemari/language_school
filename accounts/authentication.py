from django.contrib.auth.models import update_last_login
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework import serializers as drf_serializers


class TrackedTokenObtainPairSerializer(TokenObtainPairSerializer):
    """صدور توکن و ثبت زمان آخرین ورود کاربر در فیلد استاندارد Django."""

    def validate(self, attrs):
        data = super().validate(attrs)
        # این سوییچ فقط اپ موبایل را می‌بندد، نه پنل وب — فقط وقتی هدر مخصوص اپ ارسال شده باشد چک می‌شود.
        request = self.context.get('request')
        is_mobile_app = bool(request) and request.headers.get('X-Client-Platform') == 'mobile-app'
        if is_mobile_app:
            from .models import AppAccessSettings
            if not AppAccessSettings.is_role_enabled(self.user.role):
                raise drf_serializers.ValidationError({'error': 'دسترسی به اپ برای نقش شما موقتاً توسط مدیر غیرفعال شده است'})
        # زمان ورود قبلی باید قبل از به‌روزرسانی last_login خوانده شود.
        previous_last_login = self.user.last_login
        data['previous_last_login'] = previous_last_login.isoformat() if previous_last_login else None
        update_last_login(None, self.user)
        return data


class TrackedTokenObtainPairView(TokenObtainPairView):
    serializer_class = TrackedTokenObtainPairSerializer
