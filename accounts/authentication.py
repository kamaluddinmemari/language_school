from django.contrib.auth.models import update_last_login
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView


class TrackedTokenObtainPairSerializer(TokenObtainPairSerializer):
    """صدور توکن و ثبت زمان آخرین ورود کاربر در فیلد استاندارد Django."""

    def validate(self, attrs):
        data = super().validate(attrs)
        # زمان ورود قبلی باید قبل از به‌روزرسانی last_login خوانده شود.
        previous_last_login = self.user.last_login
        data['previous_last_login'] = previous_last_login.isoformat() if previous_last_login else None
        update_last_login(None, self.user)
        return data


class TrackedTokenObtainPairView(TokenObtainPairView):
    serializer_class = TrackedTokenObtainPairSerializer
