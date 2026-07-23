from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import EmployeeProfile, SalaryProfile, MonthlyPayroll, LeaveBalance, LeaveRequest
from .serializers import (
    EmployeeProfileSerializer, SalaryProfileSerializer, MonthlyPayrollSerializer,
    LeaveBalanceSerializer, LeaveRequestSerializer,
)

User = get_user_model()


def is_admin(user):
    return user.role == 'admin'


class AdminEditOwnViewMixin:
    """
    قاعده‌ی مشترک همه‌ی endpointهای این اپ: مدیر کنترل کامل روی همه دارد (ساخت/ویرایش/حذف برای هر کارمند)؛
    خودِ کارمند (نقش اداری) فقط می‌تواند رکوردهای خودش را ببیند — نه ویرایش، نه رکورد کس دیگری.
    """
    def get_queryset(self):
        qs = self.queryset_base()
        if is_admin(self.request.user):
            user_id = self.request.query_params.get('user')
            return qs.filter(user_id=user_id) if user_id else qs
        return qs.filter(user=self.request.user)

    def check_write_permission(self):
        return is_admin(self.request.user)


class EmployeeProfileListCreateView(AdminEditOwnViewMixin, generics.ListCreateAPIView):
    serializer_class = EmployeeProfileSerializer
    permission_classes = [IsAuthenticated]

    def queryset_base(self):
        return EmployeeProfile.objects.select_related('user')

    def create(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند این اطلاعات را ثبت کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class EmployeeProfileDetailView(AdminEditOwnViewMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = EmployeeProfileSerializer
    permission_classes = [IsAuthenticated]

    def queryset_base(self):
        return EmployeeProfile.objects.select_related('user')

    def update(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند ویرایش کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند حذف کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class SalaryProfileListCreateView(AdminEditOwnViewMixin, generics.ListCreateAPIView):
    serializer_class = SalaryProfileSerializer
    permission_classes = [IsAuthenticated]

    def queryset_base(self):
        return SalaryProfile.objects.select_related('user')

    def create(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند حقوق پایه را ثبت کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class SalaryProfileDetailView(AdminEditOwnViewMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SalaryProfileSerializer
    permission_classes = [IsAuthenticated]

    def queryset_base(self):
        return SalaryProfile.objects.select_related('user')

    def update(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند ویرایش کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند حذف کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class MonthlyPayrollListCreateView(AdminEditOwnViewMixin, generics.ListCreateAPIView):
    serializer_class = MonthlyPayrollSerializer
    permission_classes = [IsAuthenticated]

    def queryset_base(self):
        return MonthlyPayroll.objects.select_related('user')

    def create(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند فیش حقوقی ثبت کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class MonthlyPayrollDetailView(AdminEditOwnViewMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = MonthlyPayrollSerializer
    permission_classes = [IsAuthenticated]

    def queryset_base(self):
        return MonthlyPayroll.objects.select_related('user')

    def update(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند ویرایش کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند حذف کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class LeaveBalanceListCreateView(AdminEditOwnViewMixin, generics.ListCreateAPIView):
    serializer_class = LeaveBalanceSerializer
    permission_classes = [IsAuthenticated]

    def queryset_base(self):
        return LeaveBalance.objects.select_related('user')

    def create(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند سقف مرخصی را تعیین کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class LeaveBalanceDetailView(AdminEditOwnViewMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = LeaveBalanceSerializer
    permission_classes = [IsAuthenticated]

    def queryset_base(self):
        return LeaveBalance.objects.select_related('user')

    def update(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند ویرایش کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند حذف کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class LeaveRequestListCreateView(generics.ListCreateAPIView):
    """
    GET: مدیر همه‌ی درخواست‌ها را می‌بیند (با فیلتر اختیاری user)، کارمند فقط درخواست‌های خودش را.
    POST: مدیر برای هر کارمندی می‌تواند ثبت کند؛ کارمند فقط برای خودش (با تاریخ/ساعت همان لحظه) — بدون امکان ویرایش بعدی.
    """
    serializer_class = LeaveRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = LeaveRequest.objects.select_related('user', 'decided_by')
        if is_admin(self.request.user):
            user_id = self.request.query_params.get('user')
            return qs.filter(user_id=user_id) if user_id else qs
        return qs.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        if not is_admin(request.user):
            # کارمند فقط می‌تواند برای خودش درخواست ثبت کند
            data['user'] = request.user.id
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class LeaveRequestDetailView(generics.RetrieveUpdateDestroyAPIView):
    """فقط مدیر می‌تواند درخواست مرخصی را ویرایش/حذف کند (خودِ کارمند فقط ثبت‌کننده است، نه ویرایشگر)."""
    serializer_class = LeaveRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = LeaveRequest.objects.select_related('user', 'decided_by')
        if is_admin(self.request.user):
            return qs
        return qs.filter(user=self.request.user)

    def update(self, request, *args, **kwargs):
        if not is_admin(request.user):
            return Response({'error': 'فقط مدیر می‌تواند ویرایش کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not is_admin(request.user):
            return Response({'error': 'فقط مدیر می‌تواند حذف کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class LeaveRequestDecideView(APIView):
    """POST: تایید یا رد یک درخواست مرخصی توسط مدیر — فقط مدیر."""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not is_admin(request.user):
            return Response({'error': 'فقط مدیر می‌تواند تصمیم بگیرد'}, status=status.HTTP_403_FORBIDDEN)
        try:
            leave = LeaveRequest.objects.get(pk=pk)
        except LeaveRequest.DoesNotExist:
            return Response({'error': 'درخواست پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        decision = request.data.get('decision')
        if decision not in ('approved', 'rejected'):
            return Response({'error': "decision باید 'approved' یا 'rejected' باشد"}, status=status.HTTP_400_BAD_REQUEST)
        leave.status = decision
        leave.decided_at = timezone.now()
        leave.decided_by = request.user
        leave.save()
        return Response(LeaveRequestSerializer(leave).data)


class MonthlyPayrollAcknowledgeView(APIView):
    """
    POST: «مشاهده و تایید فیش» — فقط خودِ کارمندِ صاحبِ فیش می‌تواند بزند (نه مدیر برای او).
    تاریخ/ساعت شمسیِ همین لحظه ثبت می‌شود؛ اگر قبلاً تاییدشده باشد، همان تاریخ اول باقی می‌ماند.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            payroll = MonthlyPayroll.objects.get(pk=pk)
        except MonthlyPayroll.DoesNotExist:
            return Response({'error': 'فیش پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        if payroll.user_id != request.user.id:
            return Response({'error': 'فقط خودِ کارمند می‌تواند فیش خودش را تایید کند'}, status=status.HTTP_403_FORBIDDEN)
        if not payroll.acknowledged_at:
            payroll.acknowledged_at = timezone.now()
            payroll.save()
        return Response(MonthlyPayrollSerializer(payroll).data)
