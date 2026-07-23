from django.conf import settings
from django.db import models
from django.utils import timezone
import jdatetime

PERSIAN_MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
                   'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']

STANDARD_MONTHLY_HOURS = 220
STANDARD_DAILY_HOURS = 7.33
OVERTIME_MULTIPLIER = 1.4  # نرخ اضافه‌کاری طبق عرف رایج (۱٫۴ برابر نرخ ساعتی عادی)


class EmployeeProfile(models.Model):
    class MaritalStatus(models.TextChoices):
        SINGLE = 'single', 'مجرد'
        MARRIED = 'married', 'متاهل'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='employee_profile')
    education_degree = models.CharField(max_length=50, blank=True, help_text='مدرک تحصیلی')
    education_field = models.CharField(max_length=100, blank=True, help_text='رشته تحصیلی')
    hire_date = models.DateField(null=True, blank=True, help_text='تاریخ استخدام')
    address = models.TextField(blank=True, help_text='آدرس محل سکونت')
    marital_status = models.CharField(max_length=10, choices=MaritalStatus.choices, blank=True)
    children_count = models.PositiveIntegerField(default=0, help_text='تعداد فرزندان (در صورت تاهل)')
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def hire_date_jalali(self):
        if not self.hire_date:
            return None
        return jdatetime.date.fromgregorian(date=self.hire_date).strftime('%Y/%m/%d')

    def __str__(self):
        return f"پروفایل کارمندی {self.user.get_full_name()}"


class SalaryProfile(models.Model):
    """
    مبالغ پایه‌ی حقوق هر کارمند برای یک سال کاری مشخص (چون حداقل حقوق و مصوبات هرسال عوض می‌شوند).
    همه‌ی مبالغ زیر «ماهانه‌ی کامل» وارد می‌شوند؛ سیستم خودش معادل روزانه/ساعتی‌شان را
    (بر مبنای ۳۰ روز / ۲۲۰ ساعت استاندارد ماهانه) محاسبه و در محاسبات واقعی هر ماه، متناسب
    با ساعات کارکردِ واقعیِ آن ماه، به‌کار می‌برد.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='salary_profiles')
    work_year = models.PositiveIntegerField(help_text='سال کاری شمسی، مثلاً ۱۴۰۴')
    base_salary = models.PositiveIntegerField(default=0, help_text='حداقل حقوق پایه‌ی سال کاری (تومان، ماهانه)')
    food_allowance = models.PositiveIntegerField(default=0, help_text='حق خوار و بار (ماهانه)')
    marriage_allowance = models.PositiveIntegerField(default=0, help_text='حق تاهل (ماهانه)')
    child_allowance = models.PositiveIntegerField(default=0, help_text='حق اولاد (ماهانه)')
    seniority_allowance = models.PositiveIntegerField(default=0, help_text='سنوات سالانه — حق سنوات (معادل ماهانه‌اش اینجا وارد می‌شود)')
    # حق بیمه‌ی مصوبِ همان سال برای ۳۰ روز کامل — مبنای محاسبه‌ی خودکار حق بیمه‌ی هر ماه
    # بر اساس تعداد روزهای بیمه‌ی همان ماه (insurance_days در MonthlyPayroll)
    insurance_rate_30_days = models.PositiveIntegerField(default=0, help_text='حق بیمه‌ی مصوبِ این سال برای ۳۰ روز کامل (تومان)')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'work_year'], name='unique_salary_profile_per_user_year')]
        ordering = ['-work_year']

    @property
    def gross_base_monthly(self):
        return self.base_salary + self.food_allowance + self.marriage_allowance + self.child_allowance + self.seniority_allowance

    def _component_breakdown(self, monthly_amount):
        return {
            'monthly': monthly_amount,
            'daily': round(monthly_amount / 30) if monthly_amount else 0,
            'hourly': round(monthly_amount / STANDARD_MONTHLY_HOURS) if monthly_amount else 0,
        }

    @property
    def components_breakdown(self):
        """معادل روزانه/ساعتیِ هرکدام از اجزای حقوق — صرفاً برای نمایش به مدیر، محاسبه‌ی نهایی حقوق از گروس کلی انجام می‌شود"""
        return {
            'base_salary': self._component_breakdown(self.base_salary),
            'food_allowance': self._component_breakdown(self.food_allowance),
            'marriage_allowance': self._component_breakdown(self.marriage_allowance),
            'child_allowance': self._component_breakdown(self.child_allowance),
            'seniority_allowance': self._component_breakdown(self.seniority_allowance),
            'insurance_rate_30_days': self._component_breakdown(self.insurance_rate_30_days),
        }

    def __str__(self):
        return f"حقوق پایه {self.user.get_full_name()} — سال {self.work_year}"


class MonthlyPayroll(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payroll_records')
    jalali_year = models.PositiveIntegerField()
    jalali_month = models.PositiveIntegerField(help_text='۱ تا ۱۲')
    worked_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0, help_text='ساعات کارکرد این ماه')

    # کسورات
    insurance_days = models.PositiveIntegerField(default=30, help_text='تعداد روزهای بیمه‌ی این ماه')
    absence_days = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='غیبت (روز) — کسر می‌شود')
    absence_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='غیبت (ساعت) — کسر می‌شود')
    undertime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='کم‌کاری (ساعت) — کسر می‌شود')

    # اضافات
    overtime_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0, help_text='اضافه‌کاری (ساعت) — با نرخ ۱٫۴ برابر اضافه می‌شود')
    bonus_amount = models.PositiveIntegerField(default=0, help_text='پاداش (تومان) — مستقیم اضافه می‌شود')

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # تایید کارمند («مشاهده و تایید فیش») — فقط خودِ کارمند می‌تواند این را بزند
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'jalali_year', 'jalali_month'], name='unique_payroll_per_user_month')]
        ordering = ['-jalali_year', '-jalali_month']

    @property
    def _salary_profile(self):
        return self.user.salary_profiles.filter(work_year=self.jalali_year).order_by('-work_year').first() \
            or self.user.salary_profiles.order_by('-work_year').first()

    @property
    def gross_base_monthly(self):
        sp = self._salary_profile
        return sp.gross_base_monthly if sp else 0

    @property
    def hourly_wage(self):
        return round(self.gross_base_monthly / STANDARD_MONTHLY_HOURS) if self.gross_base_monthly else 0

    @property
    def daily_wage(self):
        return round(self.hourly_wage * STANDARD_DAILY_HOURS)

    @property
    def insurance_amount(self):
        """حق بیمه‌ی این ماه — خودکار از روی نرخ مصوب سالانه (برای ۳۰ روز) و تعداد روزهای بیمه‌ی همین ماه"""
        sp = self._salary_profile
        rate30 = sp.insurance_rate_30_days if sp else 0
        if not rate30:
            return 0
        return round(rate30 / 30 * self.insurance_days)

    @property
    def overtime_pay(self):
        return round(self.hourly_wage * OVERTIME_MULTIPLIER * float(self.overtime_hours))

    @property
    def absence_deduction(self):
        return round(self.daily_wage * float(self.absence_days) + self.hourly_wage * float(self.absence_hours))

    @property
    def undertime_deduction(self):
        return round(self.hourly_wage * float(self.undertime_hours))

    @property
    def gross_pay(self):
        """حقوق ناخالص = (حقوق ساعتی × ساعت کارکرد) + اضافه‌کاری + پاداش"""
        base = round(self.hourly_wage * float(self.worked_hours))
        return base + self.overtime_pay + self.bonus_amount

    @property
    def total_deductions(self):
        return self.insurance_amount + self.absence_deduction + self.undertime_deduction

    @property
    def net_pay(self):
        """حقوق خالص = ناخالص - (حق بیمه + کسر غیبت + کسر کم‌کاری)"""
        return max(0, self.gross_pay - self.total_deductions)

    @property
    def jalali_label(self):
        return f"{PERSIAN_MONTHS[self.jalali_month - 1]} {self.jalali_year}"

    @property
    def acknowledged_at_jalali(self):
        if not self.acknowledged_at:
            return None
        local_dt = timezone.localtime(self.acknowledged_at)
        return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')

    def __str__(self):
        return f"فیش {self.user.get_full_name()} — {self.jalali_label}"


class LeaveBalance(models.Model):
    """
    سقف مرخصیِ مجاز هر کارمند در یک سال کاری شمسی — فقط توسط مدیر تعیین می‌شود.
    مرخصی روزانه سالانه حساب می‌شود (annual_days)، ولی مرخصی ساعتی طبق درخواست کاربر
    ماهانه است: هر ماه دوباره به‌اندازه‌ی monthly_hourly_allowance شارژ می‌شود و مصرفِ
    هر ماه جدا از ماه‌های دیگر محاسبه می‌شود (مثل «هرماه سهمیه‌ی تازه»، نه یک استخر سالانه).
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_balances')
    jalali_year = models.PositiveIntegerField()
    annual_days = models.PositiveIntegerField(default=0, help_text='عدد مرخصی روزانه‌ی مجاز در این سال')
    monthly_hourly_allowance = models.DecimalField(max_digits=6, decimal_places=2, default=0, help_text='مقدار مجاز مرخصی ساعتی — در هر ماه (نه کل سال)')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'jalali_year'], name='unique_leave_balance_per_user_year')]
        ordering = ['-jalali_year']

    def _approved_requests(self):
        return self.user.leave_requests.filter(status=LeaveRequest.Status.APPROVED)

    @property
    def used_days(self):
        total = 0
        for r in self._approved_requests().filter(leave_type=LeaveRequest.LeaveType.DAILY):
            jy = jdatetime.date.fromgregorian(date=r.start_date).year
            if jy == self.jalali_year:
                total += r.days_count
        return total

    @property
    def remaining_days(self):
        return self.annual_days - self.used_days

    def hours_used_in_month(self, jalali_month):
        total = 0
        for r in self._approved_requests().filter(leave_type=LeaveRequest.LeaveType.HOURLY):
            jd = jdatetime.date.fromgregorian(date=r.start_date)
            if jd.year == self.jalali_year and jd.month == jalali_month:
                total += float(r.hours or 0)
        return total

    def hours_remaining_in_month(self, jalali_month):
        return float(self.monthly_hourly_allowance) - self.hours_used_in_month(jalali_month)

    @property
    def monthly_hourly_breakdown(self):
        """مصرف/باقیمانده‌ی مرخصی ساعتی به‌تفکیک هر ۱۲ ماه سال جاری"""
        return [
            {
                'jalali_month': m, 'month_label': PERSIAN_MONTHS[m - 1],
                'used_hours': self.hours_used_in_month(m),
                'remaining_hours': self.hours_remaining_in_month(m),
            }
            for m in range(1, 13)
        ]

    def __str__(self):
        return f"مانده مرخصی {self.user.get_full_name()} — سال {self.jalali_year}"


class LeaveRequest(models.Model):
    class LeaveType(models.TextChoices):
        DAILY = 'daily', 'روزانه'
        HOURLY = 'hourly', 'ساعتی'

    class LeaveCategory(models.TextChoices):
        ENTITLED = 'entitled', 'استحقاقی'
        SICK = 'sick', 'استعلاجی'
        OTHER = 'other', 'سایر'

    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار تایید'
        APPROVED = 'approved', 'تایید شده'
        REJECTED = 'rejected', 'رد شده'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.CharField(max_length=10, choices=LeaveType.choices, default=LeaveType.DAILY)
    leave_category = models.CharField(max_length=10, choices=LeaveCategory.choices, default=LeaveCategory.ENTITLED)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text='برای مرخصی روزانه‌ی چندروزه')
    hours = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text='برای مرخصی ساعتی')
    reason = models.CharField(max_length=255, blank=True, help_text='برای دسته‌ی «سایر» الزامی است')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['-requested_at']

    @property
    def days_count(self):
        if self.leave_type != self.LeaveType.DAILY:
            return 0
        end = self.end_date or self.start_date
        return (end - self.start_date).days + 1

    @property
    def start_date_jalali(self):
        return jdatetime.date.fromgregorian(date=self.start_date).strftime('%Y/%m/%d')

    @property
    def end_date_jalali(self):
        if not self.end_date:
            return None
        return jdatetime.date.fromgregorian(date=self.end_date).strftime('%Y/%m/%d')

    @property
    def requested_at_jalali(self):
        local_dt = timezone.localtime(self.requested_at)
        return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')

    @property
    def decided_at_jalali(self):
        if not self.decided_at:
            return None
        return jdatetime.datetime.fromgregorian(datetime=timezone.localtime(self.decided_at)).strftime('%Y/%m/%d - %H:%M')

    def __str__(self):
        return f"مرخصی {self.user.get_full_name()} — {self.start_date_jalali}"
