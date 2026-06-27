from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.utils import timezone
from datetime import timedelta
import random
from .models import User, OTPCode, PriceSetting
from .serializers import (
    RegisterSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    UserProfileSerializer,
    TeacherSerializer,
    PriceSettingSerializer
)


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer


class ForgotPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if serializer.is_valid():
            phone = serializer.validated_data['phone']
            try:
                user = User.objects.get(phone=phone)
            except User.DoesNotExist:
                return Response(
                    {'error': 'کاربری با این شماره پیدا نشد'},
                    status=status.HTTP_404_NOT_FOUND
                )
            code = str(random.randint(100000, 999999))
            expires_at = timezone.now() + timedelta(minutes=5)
            OTPCode.objects.create(
                user=user,
                code=code,
                expires_at=expires_at
            )
            print(f'کد OTP برای {phone}: {code}')
            return Response(
                {'message': 'کد تایید ارسال شد'},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResetPasswordView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if serializer.is_valid():
            phone = serializer.validated_data['phone']
            code = serializer.validated_data['code']
            new_password = serializer.validated_data['new_password']
            try:
                user = User.objects.get(phone=phone)
                otp = OTPCode.objects.filter(
                    user=user,
                    code=code,
                    is_used=False,
                    expires_at__gt=timezone.now()
                ).latest('created_at')
            except (User.DoesNotExist, OTPCode.DoesNotExist):
                return Response(
                    {'error': 'کد نامعتبر یا منقضی شده'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            user.set_password(new_password)
            user.save()
            otp.is_used = True
            otp.save()
            return Response(
                {'message': 'رمز عبور با موفقیت تغییر کرد'},
                status=status.HTTP_200_OK
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserProfileView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    def get_object(self):
        return self.request.user


class TeacherListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TeacherSerializer

    def get_queryset(self):
        if self.request.user.role != 'admin':
            return User.objects.none()
        return User.objects.filter(role='teacher')

    def create(self, request, *args, **kwargs):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تونه استاد اضافه کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class TeacherDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TeacherSerializer

    def get_queryset(self):
        return User.objects.filter(role='teacher')

    def check_admin(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر دسترسی دارد'}, status=status.HTTP_403_FORBIDDEN)
        return None

    def update(self, request, *args, **kwargs):
        denied = self.check_admin(request)
        if denied:
            return denied
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        denied = self.check_admin(request)
        if denied:
            return denied
        return super().destroy(request, *args, **kwargs)


class PriceSettingView(APIView):
    """
    تنظیمات قیمت فعلی. هر کاربر لاگین‌شده (مثلاً اپ دانش‌آموز برای پیش‌نمایش قیمت)
    می‌تواند بخواند؛ فقط مدیر می‌تواند تغییر دهد.
    """
    permission_classes = [IsAuthenticated]

    def get_current(self):
        price_setting = PriceSetting.objects.order_by('-updated_at').first()
        if not price_setting:
            price_setting = PriceSetting.objects.create()
        return price_setting

    def get(self, request):
        serializer = PriceSettingSerializer(self.get_current())
        return Response(serializer.data)

    def patch(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تونه قیمت رو تغییر بده'}, status=status.HTTP_403_FORBIDDEN)
        price_setting = self.get_current()
        serializer = PriceSettingSerializer(price_setting, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(updated_by=request.user)
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)