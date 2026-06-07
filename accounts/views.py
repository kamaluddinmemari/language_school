from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.utils import timezone
from datetime import timedelta
import random
from .models import User, OTPCode
from .serializers import (
    RegisterSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
    UserProfileSerializer
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