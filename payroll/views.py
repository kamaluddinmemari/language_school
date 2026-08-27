from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.contrib.auth import get_user_model

from .models import EmployeeProfile, SalaryProfile, MonthlyPayroll, LeaveBalance, LeaveRequest, AttendanceLog
from .serializers import (
    EmployeeProfileSerializer, SalaryProfileSerializer, MonthlyPayrollSerializer,
    LeaveBalanceSerializer, LeaveRequestSerializer, AttendanceLogSerializer,
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
    """
    تنظیمات پایه‌ی حقوق — مشترک برای همه‌ی کارمندان، نه مخصوص یک نفر؛ همه (مدیر و کارمند) می‌توانند
    ببینند، فقط مدیر می‌تواند ثبت/ویرایش کند. یک رکورد به ازای هر سال کاری (work_year یکتاست).
    """
    serializer_class = SalaryProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SalaryProfile.objects.all()

    def create(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند حقوق پایه را ثبت کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class SalaryProfileDetailView(AdminEditOwnViewMixin, generics.RetrieveUpdateDestroyAPIView):
    serializer_class = SalaryProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return SalaryProfile.objects.all()

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
        # اگه ساعت کارکرد صریحاً نیومده بود، به‌صورت پیش‌فرض از AttendanceLog همون ماه محاسبه می‌شه
        # (ولی همچنان دستی هم قابل‌جایگزینی/ویرایش هست، چون فقط پیش‌فرضِ اولیه‌ست)
        data = request.data.copy()
        if 'worked_hours' not in data or data.get('worked_hours') in (None, ''):
            try:
                user_id = int(data.get('user'))
                jy = int(data.get('jalali_year'))
                jm = int(data.get('jalali_month'))
                temp = MonthlyPayroll(user_id=user_id, jalali_year=jy, jalali_month=jm)
                data['worked_hours'] = temp.auto_worked_hours
            except (TypeError, ValueError):
                pass
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


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



def approved_daily_leave(user, day):
    return LeaveRequest.objects.filter(user=user, status=LeaveRequest.Status.APPROVED, leave_type=LeaveRequest.LeaveType.DAILY, start_date__lte=day).filter(Q(end_date__gte=day) | Q(end_date__isnull=True)).first()

# ==================== ثبت ساعت ورود و خروج (AttendanceLog) ====================

class MyAttendanceTodayView(APIView):
    """GET: وضعیت ثبت ورود/خروج خودِ کارمند برای همین امروز — برای فعال/غیرفعال کردن دکمه‌های سبز/قرمز داشبورد"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.localtime(timezone.now()).date()
        leave = approved_daily_leave(request.user, today)
        if leave:
            return Response({'error': 'کارمند در مرخصی می‌باشد', 'on_leave': True, 'leave_shift': leave.leave_shift, 'leave_credited_hours': leave.credited_hours_label}, status=status.HTTP_400_BAD_REQUEST)
        log = AttendanceLog.objects.filter(user=request.user, date=today).first()
        leave = approved_daily_leave(request.user, today)
        payload = AttendanceLogSerializer(log).data if log else {'date': today.isoformat(), 'check_in': None, 'check_out': None}
        payload.update({'on_leave': bool(leave), 'leave_message': 'کارمند در مرخصی می‌باشد' if leave else None, 'leave_shift': leave.leave_shift if leave else None, 'leave_credited_hours': leave.credited_hours_label if leave else None})
        return Response(payload)


class CheckInView(APIView):
    """POST: دکمه‌ی سبز «ثبت ورود» — فقط یک‌بار در روز، توسط خودِ کارمند، غیرقابل‌ویرایش برای خودش"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        today = timezone.localtime(timezone.now()).date()
        leave = approved_daily_leave(request.user, today)
        if leave:
            return Response({'error': 'کارمند در مرخصی می‌باشد', 'on_leave': True, 'leave_shift': leave.leave_shift, 'leave_credited_hours': leave.credited_hours_label}, status=status.HTTP_400_BAD_REQUEST)
        log, created = AttendanceLog.objects.get_or_create(user=request.user, date=today)
        if log.check_in:
            return Response({'error': f'شما امروز ساعت {log.check_in_time_jalali} ورودتان ثبت شده — هر روز فقط یک‌بار قابل ثبت است'}, status=status.HTTP_400_BAD_REQUEST)
        log.check_in = timezone.now()
        log.save(update_fields=['check_in', 'updated_at'])
        return Response(AttendanceLogSerializer(log).data, status=status.HTTP_201_CREATED)


class CheckOutView(APIView):
    """POST: دکمه‌ی قرمز «ثبت خروج» — فقط یک‌بار در روز، توسط خودِ کارمند، غیرقابل‌ویرایش برای خودش"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        today = timezone.localtime(timezone.now()).date()
        log = AttendanceLog.objects.filter(user=request.user, date=today).first()
        if not log or not log.check_in:
            return Response({'error': 'اول باید ورودتان را ثبت کنید'}, status=status.HTTP_400_BAD_REQUEST)
        if log.check_out:
            return Response({'error': f'شما امروز ساعت {log.check_out_time_jalali} خروجتان ثبت شده — هر روز فقط یک‌بار قابل ثبت است'}, status=status.HTTP_400_BAD_REQUEST)
        log.check_out = timezone.now()
        log.save(update_fields=['check_out', 'updated_at'])
        return Response(AttendanceLogSerializer(log).data)


class AttendanceLogListCreateView(AdminEditOwnViewMixin, generics.ListCreateAPIView):
    """GET: مدیر لیست کامل (با فیلتر user/تاریخ)، کارمند فقط لیست خودش. POST: فقط مدیر (برای اصلاح دستی/افزودن رکورد فراموش‌شده)"""
    serializer_class = AttendanceLogSerializer
    permission_classes = [IsAuthenticated]

    def queryset_base(self):
        qs = AttendanceLog.objects.select_related('user')
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(date__gte=date_from)
        if date_to:
            qs = qs.filter(date__lte=date_to)
        return qs

    def create(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند رکورد حضور دستی ثبت کند'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data.copy()
        data['edited_by_admin'] = True
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class AttendanceLogDetailView(AdminEditOwnViewMixin, generics.RetrieveUpdateDestroyAPIView):
    """فقط مدیر می‌تواند ساعت/تاریخ ورود-خروج ثبت‌شده را دستی اصلاح یا حذف کند"""
    serializer_class = AttendanceLogSerializer
    permission_classes = [IsAuthenticated]

    def queryset_base(self):
        return AttendanceLog.objects.select_related('user')

    def update(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند اصلاح کند'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data.copy()
        data['edited_by_admin'] = True
        serializer = self.get_serializer(self.get_object(), data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        if not self.check_write_permission():
            return Response({'error': 'فقط مدیر می‌تواند حذف کند'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class AttendanceSummaryView(APIView):
    """
    GET: خلاصه‌ی ساعات کارکرد روزانه/هفتگی/ماهانه‌ی یک کارمند — مدیر با ?user=<id>، کارمند برای خودش.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        target_user = request.user
        if is_admin(request.user):
            user_id = request.query_params.get('user')
            if user_id:
                try:
                    target_user = User.objects.get(pk=user_id)
                except User.DoesNotExist:
                    return Response({'error': 'کارمند پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)
        elif request.query_params.get('user') and str(request.query_params.get('user')) != str(request.user.id):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        today = timezone.localtime(timezone.now()).date()
        today_jalali = __import__('jdatetime').date.fromgregorian(date=today)

        def hours_minutes(value):
            total_minutes = max(0, round(float(value or 0) * 60))
            return f'{total_minutes // 60} ساعت و {total_minutes % 60:02d} دقیقه'

        logs = AttendanceLog.objects.filter(user=target_user).order_by('-date')

        # امروز
        today_log = logs.filter(date=today).first()
        today_hours = today_log.worked_hours if today_log else 0

        # همین هفته‌ی شمسی (شنبه تا امروز)
        weekday = (today_jalali.weekday() + 1) % 7  # jdatetime: شنبه=0
        week_start = today - timezone.timedelta(days=(today_jalali.weekday()))
        week_hours = sum(l.worked_hours for l in logs if l.date >= week_start)

        # همین ماه شمسی
        month_hours = 0.0
        daily_breakdown = []
        for l in logs:
            jd = __import__('jdatetime').date.fromgregorian(date=l.date)
            if jd.year == today_jalali.year and jd.month == today_jalali.month:
                month_hours += l.worked_hours
                daily_breakdown.append({
                    'date_jalali': l.date_jalali, 'check_in': l.check_in_time_jalali,
                    'check_out': l.check_out_time_jalali, 'worked_hours': l.worked_hours,
                    'worked_hours_label': hours_minutes(l.worked_hours),
                })

        return Response({
            'user': target_user.id, 'user_full_name': target_user.get_full_name(),
            'today_hours': today_hours,
            'today_hours_label': hours_minutes(today_hours),
            'week_hours': round(week_hours, 2),
            'week_hours_label': hours_minutes(week_hours),
            'month_hours': round(month_hours, 2),
            'month_hours_label': hours_minutes(month_hours),
            'jalali_year': today_jalali.year, 'jalali_month': today_jalali.month,
            'daily_breakdown': sorted(daily_breakdown, key=lambda x: x['date_jalali']),
        })
