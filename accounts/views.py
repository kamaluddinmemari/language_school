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
    PriceSettingSerializer,
    StudentSerializer,
    UserRoleSerializer
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
        return User.objects.filter(role__in=User.TEACHER_LIKE_ROLES)

    def create(self, request, *args, **kwargs):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تونه استاد اضافه کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class TeacherDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TeacherSerializer

    def get_queryset(self):
        return User.objects.filter(role__in=User.TEACHER_LIKE_ROLES)

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


class StudentListView(generics.ListCreateAPIView):
    """لیست + افزودن دانش‌آموز جدید (هم آن‌هایی که از کانتر ثبت شدند هم از طریق اپ) — فقط برای مدیر"""
    permission_classes = [IsAuthenticated]
    serializer_class = StudentSerializer

    def get_queryset(self):
        if self.request.user.role != 'admin':
            return User.objects.none()
        return User.objects.filter(role='student').order_by('-id')

    def create(self, request, *args, **kwargs):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تونه دانش‌آموز اضافه کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class StudentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """ویرایش/حذف مشخصات یک دانش‌آموز (نام، نام‌خانوادگی، موبایل، کد ملی، سطح) — فقط برای مدیر"""
    permission_classes = [IsAuthenticated]
    serializer_class = StudentSerializer

    def get_queryset(self):
        return User.objects.filter(role='student')

    def update(self, request, *args, **kwargs):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تونه ویرایش کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تونه حذف کنه'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class UserRoleView(APIView):
    """تغییر نقش هر کاربری (مثلاً ارتقای کاربری که از اپ ثبت‌نام کرده) — فقط برای مدیر"""
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تونه نقش رو تغییر بده'}, status=status.HTTP_403_FORBIDDEN)
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({'error': 'کاربر پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        new_role = request.data.get('role')
        if new_role not in [User.Role.ADMIN, User.Role.TEACHER, User.Role.STUDENT, User.Role.EVALUATOR]:
            return Response({'error': 'نقش نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)

        user.role = new_role
        user.save()
        return Response(UserRoleSerializer(user).data)


class PeopleSearchView(APIView):
    """
    جستجوی سراسری افراد بر اساس کد ملی، نام، یا نام‌خانوادگی، برای پرکردن خودکار فرم‌ها با اطلاعات
    قبلاً ثبت‌شده (دانش‌آموزان، لیست انتظار ورودی جدید، زبان‌آموزان ثبت‌نام‌نشده، بدهکاران) —
    تا کاربر مجبور به تایپ دوباره‌ی اطلاعات یک نفر که قبلاً جایی ثبت شده نباشد.
    فقط برای مدیر/مسئول آموزش (کسانی که این فرم‌ها را پر می‌کنند).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in ('admin', 'evaluator'):
            return Response([])
        q = request.query_params.get('q', '').strip()
        if len(q) < 2:
            return Response([])

        from django.db.models import Q
        results = []
        seen = set()

        def add(first_name, last_name, father_name, national_code, phone, phone2, source):
            key = (national_code or '', phone or '', first_name, last_name)
            if key in seen:
                return
            seen.add(key)
            results.append({
                'first_name': first_name, 'last_name': last_name, 'father_name': father_name or '',
                'national_code': national_code or '', 'phone': phone or '', 'phone2': phone2 or '',
                'source': source,
            })

        students = User.objects.filter(role='student').filter(
            Q(national_code__icontains=q) | Q(last_name__icontains=q) | Q(first_name__icontains=q)
        )[:8]
        for s in students:
            add(s.first_name, s.last_name, s.father_name, s.national_code, s.phone, s.phone2, 'دانش‌آموز')

        try:
            from leads.models import NewLead, UnregisteredStudent, Debtor, DiscountedPerson
            for lead in NewLead.objects.filter(Q(national_code__icontains=q) | Q(last_name__icontains=q) | Q(first_name__icontains=q))[:8]:
                add(lead.first_name, lead.last_name, lead.father_name, lead.national_code, lead.phone, '', 'لیست انتظار')
            for us in UnregisteredStudent.objects.filter(Q(national_code__icontains=q) | Q(last_name__icontains=q) | Q(first_name__icontains=q))[:8]:
                add(us.first_name, us.last_name, '', us.national_code, us.phone, '', 'ثبت‌نام‌نشده')
            for d in Debtor.objects.filter(Q(last_name__icontains=q) | Q(first_name__icontains=q))[:8]:
                add(d.first_name, d.last_name, '', '', d.phone, '', 'بدهکار')
            for dp in DiscountedPerson.objects.filter(Q(national_code__icontains=q) | Q(last_name__icontains=q) | Q(first_name__icontains=q))[:8]:
                add(dp.first_name, dp.last_name, '', dp.national_code, '', '', 'دارای تخفیف')
        except ImportError:
            pass

        return Response(results[:10])