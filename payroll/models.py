from django.conf import settings
from django.db import models
import jdatetime

PERSIAN_MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
                   'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']

STANDARD_MONTHLY_HOURS = 220
STANDARD_DAILY_HOURS = 7.33


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
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='salary_profiles')
    work_year = models.PositiveIntegerField(help_text='سال کاری شمسی، مثلاً ۱۴۰۴')
    base_salary = models.PositiveIntegerField(default=0, help_text='حداقل حقوق پایه‌ی سال کاری (تومان)')
    food_allowance = models.PositiveIntegerField(default=0, help_text='حق خوار و بار')
    marriage_allowance = models.PositiveIntegerField(default=0, help_text='حق تاهل')
    child_allowance = models.PositiveIntegerField(default=0, help_text='حق اولاد')
    seniority_allowance = models.PositiveIntegerField(default=0, help_text='سنوات سالانه (حق سنوات)')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'work_year'], name='unique_salary_profile_per_user_year')]
        ordering = ['-work_year']

    @property
    def gross_base_monthly(self):
        return self.base_salary + self.food_allowance + self.marriage_allowance + self.child_allowance + self.seniority_allowance

    def __str__(self):
        return f"حقوق پایه {self.user.get_full_name()} — سال {self.work_year}"


class MonthlyPayroll(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payroll_records')
    jalali_year = models.PositiveIntegerField()
    jalali_month = models.PositiveIntegerField(help_text='۱ تا ۱۲')
    worked_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0, help_text='ساعات کارکرد این ماه')
    insurance_days = models.PositiveIntegerField(default=30, help_text='تعداد روزهای بیمه‌ی این ماه (کسورات)')
    insurance_amount = models.PositiveIntegerField(default=0, help_text='حق بیمه‌ی ماهانه — کسر می‌شود (تومان)')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

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
    def gross_pay(self):
        return round(self.hourly_wage * float(self.worked_hours))

    @property
    def net_pay(self):
        return max(0, self.gross_pay - self.insurance_amount)

    @property
    def jalali_label(self):
        return f"{PERSIAN_MONTHS[self.jalali_month - 1]} {self.jalali_year}"

    def __str__(self):
        return f"فیش {self.user.get_full_name()} — {self.jalali_label}"


class LeaveBalance(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_balances')
    jalali_year = models.PositiveIntegerField()
    annual_days = models.PositiveIntegerField(default=0, help_text='عدد مرخصی روزانه‌ی مجاز در این سال')
    hourly_allowance = models.DecimalField(max_digits=6, decimal_places=2, default=0, help_text='مقدار مجاز مرخصی ساعتی در این سال')

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
    def used_hours(self):
        total = 0
        for r in self._approved_requests().filter(leave_type=LeaveRequest.LeaveType.HOURLY):
            jy = jdatetime.date.fromgregorian(date=r.start_date).year
            if jy == self.jalali_year:
                total += float(r.hours or 0)
        return total

    @property
    def remaining_days(self):
        return self.annual_days - self.used_days

    @property
    def remaining_hours(self):
        return float(self.hourly_allowance) - self.used_hours

    def __str__(self):
        return f"مانده مرخصی {self.user.get_full_name()} — سال {self.jalali_year}"


class LeaveRequest(models.Model):
    class LeaveType(models.TextChoices):
        DAILY = 'daily', 'روزانه'
        HOURLY = 'hourly', 'ساعتی'

    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار تایید'
        APPROVED = 'approved', 'تایید شده'
        REJECTED = 'rejected', 'رد شده'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.CharField(max_length=10, choices=LeaveType.choices, default=LeaveType.DAILY)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text='برای مرخصی روزانه‌ی چندروزه')
    hours = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, help_text='برای مرخصی ساعتی')
    reason = models.CharField(max_length=255, blank=True)
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
        local_dt = jdatetime.datetime.fromgregorian(datetime=self.requested_at)
        return local_dt.strftime('%Y/%m/%d - %H:%M')

    @property
    def decided_at_jalali(self):
        if not self.decided_at:
            return None
        return jdatetime.datetime.fromgregorian(datetime=self.decided_at).strftime('%Y/%m/%d - %H:%M')

    def __str__(self):
        return f"مرخصی {self.user.get_full_name()} — {self.start_date_jalali}"
