from django.conf import settings
from django.db import models
from django.utils import timezone
import jdatetime

PERSIAN_MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور',
                   'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند']

STANDARD_MONTHLY_HOURS = 220
STANDARD_DAILY_HOURS = 7.33
OVERTIME_MULTIPLIER = 1.4  # نرخ اضافه‌کاری طبق عرف رایج (۱٫۴ برابر نرخ ساعتی عادی)
EMPLOYEE_INSURANCE_RATE = 0.07  # سهم بیمه‌ی کارمند (۷٪ مزد مبنای بیمه)


def days_in_jalali_month(jy, jm):
    """تعداد روزهای واقعی یک ماه شمسی (۳۱/۳۰/۲۹ یا ۳۰ برای اسفند کبیسه) —
    این تابع دقیقاً همون چیزیه که باعث می‌شه محاسبات حقوق خودکار ماه ۳۰ و ۳۱
    روزه رو لحاظ کنن، به‌جای فرض ثابت ۳۰ روز."""
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    start_of_esfand = jdatetime.date(jy, 12, 1).togregorian()
    start_of_next_year = jdatetime.date(jy + 1, 1, 1).togregorian()
    return (start_of_next_year - start_of_esfand).days


_PERSIAN_ONES = ['', 'یک', 'دو', 'سه', 'چهار', 'پنج', 'شش', 'هفت', 'هشت', 'نه']
_PERSIAN_TENS_TEEN = ['ده', 'یازده', 'دوازده', 'سیزده', 'چهارده', 'پانزده', 'شانزده', 'هفده', 'هجده', 'نوزده']
_PERSIAN_TENS = ['', '', 'بیست', 'سی', 'چهل', 'پنجاه', 'شصت', 'هفتاد', 'هشتاد', 'نود']
_PERSIAN_HUNDREDS = ['', 'صد', 'دویست', 'سیصد', 'چهارصد', 'پانصد', 'ششصد', 'هفتصد', 'هشتصد', 'نهصد']
_PERSIAN_SCALES = ['', ' هزار', ' میلیون', ' میلیارد', ' بیلیون']


def _three_digit_to_words(n):
    if n == 0:
        return ''
    parts = []
    hundred, rem = divmod(n, 100)
    if hundred:
        parts.append(_PERSIAN_HUNDREDS[hundred])
    if rem:
        if rem < 10:
            parts.append(_PERSIAN_ONES[rem])
        elif rem < 20:
            parts.append(_PERSIAN_TENS_TEEN[rem - 10])
        else:
            tens, ones = divmod(rem, 10)
            if ones:
                parts.append(_PERSIAN_TENS[tens] + ' و ' + _PERSIAN_ONES[ones])
            else:
                parts.append(_PERSIAN_TENS[tens])
    return ' و '.join(parts)


def number_to_persian_words(n):
    """تبدیل یک عدد صحیح (مثلاً مبلغ حقوق) به حروف فارسی — بدون هیچ پکیج خارجی"""
    n = int(round(n))
    if n == 0:
        return 'صفر'
    if n < 0:
        return 'منفی ' + number_to_persian_words(-n)

    groups = []
    temp = n
    while temp > 0:
        groups.append(temp % 1000)
        temp //= 1000

    parts = []
    for i in range(len(groups) - 1, -1, -1):
        if groups[i] == 0:
            continue
        words = _three_digit_to_words(groups[i])
        parts.append(words + _PERSIAN_SCALES[i])
    return ' و '.join(parts)



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
    sheba_number = models.CharField(max_length=26, blank=True, help_text='شماره شبا (بدون IR)')
    bank_account_number = models.CharField(max_length=30, blank=True, help_text='شماره حساب بانکی')
    card_number = models.CharField(max_length=16, blank=True, help_text='شماره کارت بانکی')
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
    seniority_allowance = models.PositiveIntegerField(default=0, help_text='(قدیمی/غیرفعال — دیگر استفاده نمی‌شود) از این پس «پایه سنوات» خودکار از روی سابقه‌کار محاسبه می‌شود؛ این فیلد فقط برای سازگاری با داده‌های قبلی نگه داشته شده')
    housing_allowance_yearly = models.PositiveIntegerField(default=0, help_text='(قدیمی/غیرفعال — دیگر استفاده نمی‌شود) حق مسکن سالانه؛ برای سازگاری با داده‌های قبلی نگه داشته شده')
    housing_allowance = models.PositiveIntegerField(default=0, help_text='حق مسکن ماهانه (تومان) — مستقیم ماهانه وارد می‌شود')
    # مزد مبنای بیمه (برای ۳۰ روز کامل) — طبق قانون برای متاهل و مجرد می‌تواند فرق کند
    # (چون اجزای تشکیل‌دهنده‌ی مزد مبنای بیمه‌ی متاهل معمولاً حق تاهل/اولاد را هم شامل می‌شود)
    insurance_base_single = models.PositiveIntegerField(default=0, help_text='مزد مبنای بیمه برای کارمند مجرد (۳۰ روز کامل، تومان)')
    insurance_base_married = models.PositiveIntegerField(default=0, help_text='مزد مبنای بیمه برای کارمند متاهل (۳۰ روز کامل، تومان)')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'work_year'], name='unique_salary_profile_per_user_year')]
        ordering = ['-work_year']

    @property
    def housing_allowance_monthly(self):
        """حق مسکن ماهانه — مستقیم از فیلد housing_allowance؛ اگر هنوز مقدار قدیمیِ سالانه ثبت شده
        ولی مقدار ماهانه‌ی جدید صفر باشد، برای سازگاری با داده‌های قبلی از آن استفاده می‌شود"""
        if self.housing_allowance:
            return self.housing_allowance
        return round(self.housing_allowance_yearly / 12) if self.housing_allowance_yearly else 0

    def tenure_years(self, as_of=None):
        """سابقه‌ی کارِ کامل (سال) بر اساس تاریخ استخدام در پروفایل کارمندی — برای محاسبه‌ی سنوات"""
        try:
            hire_date = self.user.employee_profile.hire_date
        except Exception:
            hire_date = None
        if not hire_date:
            return 0
        today = as_of or timezone.now().date()
        years = today.year - hire_date.year - ((today.month, today.day) < (hire_date.month, hire_date.day))
        return max(0, years)

    @property
    def is_seniority_eligible(self):
        """طبق قانون کار، فقط افرادی که بیش از یک سال سابقه‌کار دارند مشمول حق سنوات می‌شوند"""
        return self.tenure_years() >= 1

    @property
    def seniority_basis_monthly(self):
        """مبنای محاسبه‌ی سنوات — «آخرین حقوق و مزایای ثابت ماهانه» بدون خودِ سنوات (برای جلوگیری از محاسبه‌ی حلقوی)"""
        return self.base_salary + self.food_allowance + self.marriage_allowance + self.child_allowance + self.housing_allowance_monthly

    @property
    def seniority_base_annual(self):
        """
        پایه سنوات سالانه — طبق عرف رایج قانون کار (یک روز مزد به ازای هر ماه کارکرد؛ یعنی معادل
        یک ماه آخرین حقوق و مزایای ثابت، به ازای هر سال سابقه‌ی تکمیل‌شده). فقط برای افرادی با
        بیش از یک سال سابقه محاسبه می‌شود.
        """
        if not self.is_seniority_eligible:
            return 0
        return self.seniority_basis_monthly

    @property
    def seniority_base_monthly(self):
        """معادل ماهانه‌ی پایه سنوات — کل سالانه تقسیم بر ۱۲، که در فیش حقوقی هر ماه اضافه می‌شود"""
        return round(self.seniority_base_annual / 12) if self.seniority_base_annual else 0

    @property
    def seniority_base_daily(self):
        return round(self.seniority_base_monthly / 30) if self.seniority_base_monthly else 0

    @property
    def seniority_base_hourly(self):
        return round(self.seniority_base_monthly / STANDARD_MONTHLY_HOURS) if self.seniority_base_monthly else 0

    @property
    def gross_base_monthly(self):
        return (self.base_salary + self.food_allowance + self.marriage_allowance +
                self.child_allowance + self.seniority_base_monthly + self.housing_allowance_monthly)

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
            'seniority_base': self._component_breakdown(self.seniority_base_monthly),
            'housing_allowance': self._component_breakdown(self.housing_allowance_monthly),
        }

    def __str__(self):
        return f"حقوق پایه {self.user.get_full_name()} — سال {self.work_year}"


class MonthlyPayroll(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payroll_records')
    jalali_year = models.PositiveIntegerField()
    jalali_month = models.PositiveIntegerField(help_text='۱ تا ۱۲')
    worked_hours = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text='ساعات کارکرد این ماه — فعلاً دستی وارد و قابل‌ویرایش است. '
                   'در آینده وقتی صفحه‌ی «ثبت ورود و خروج» ساخته شد، باید این مقدار '
                   'به‌صورت خودکار از آنجا محاسبه و پر شود، ولی همچنان دستی هم قابل‌اصلاح بماند.'
    )

    # کسورات
    insurance_days = models.PositiveIntegerField(default=30, help_text='تعداد روزهای بیمه‌ی این ماه')
    absence_days = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='غیبت (روز) — کسر می‌شود')
    absence_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='غیبت (ساعت) — کسر می‌شود')
    undertime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='کم‌کاری (ساعت) — کسر می‌شود')

    # اضافات
    overtime_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0, help_text='اضافه‌کاری (ساعت) — با نرخ ۱٫۴ برابر اضافه می‌شود')
    bonus_amount = models.PositiveIntegerField(default=0, help_text='پاداش (تومان) — مستقیم اضافه می‌شود')
    extra_payment = models.PositiveIntegerField(default=0, help_text='اضافه‌پرداخت این ماه (تومان) — مستقیم به ناخالص اضافه می‌شود')

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
    def marital_status(self):
        try:
            return self.user.employee_profile.marital_status
        except Exception:
            return ''

    @property
    def marital_status_display(self):
        return {'single': 'مجرد', 'married': 'متاهل'}.get(self.marital_status, '—')

    @property
    def children_count(self):
        try:
            return self.user.employee_profile.children_count
        except Exception:
            return 0

    @property
    def seniority_base_monthly(self):
        sp = self._salary_profile
        return sp.seniority_base_monthly if sp else 0

    @property
    def seniority_base_daily(self):
        sp = self._salary_profile
        return sp.seniority_base_daily if sp else 0

    @property
    def seniority_base_hourly(self):
        sp = self._salary_profile
        return sp.seniority_base_hourly if sp else 0

    @property
    def is_seniority_eligible(self):
        sp = self._salary_profile
        return sp.is_seniority_eligible if sp else False

    @property
    def auto_worked_hours(self):
        """
        ساعات کارکردِ خودکار — از روی ثبت‌های ورود/خروجِ (AttendanceLog) همین کارمند در همین ماه
        شمسی محاسبه می‌شود. فقط برای نمایش راهنما (کم‌رنگ) در کنار فیلد قابل‌ویرایش worked_hours
        استفاده می‌شود؛ خودِ worked_hours همچنان مقدار نهایی و قابل‌ویرایش دستی است.
        """
        logs = AttendanceLog.objects.filter(user=self.user)
        total = 0.0
        for log in logs:
            jd = jdatetime.date.fromgregorian(date=log.date)
            if jd.year == self.jalali_year and jd.month == self.jalali_month:
                total += log.worked_hours
        return round(total, 2)

    @property
    def component_amounts_this_month(self):
        """
        معادلِ ریالیِ هرکدام از اجزای حقوق (پایه، خوار و بار، تاهل، اولاد، سنوات، مسکن)، متناسب با
        نسبت ساعات کارکرد واقعیِ این ماه به ساعت استاندارد همین ماه — برای نمایش تفکیکی در فیش حقوقی.
        """
        sp = self._salary_profile
        if not sp:
            return {}
        std_hours = self.standard_monthly_hours_this_month
        ratio = (float(self.worked_hours) / std_hours) if std_hours else 0
        breakdown = sp.components_breakdown
        result = {}
        total = 0
        for key, comp in breakdown.items():
            amount = round(comp['monthly'] * ratio)
            result[key] = amount
            total += amount
        result['total'] = total
        return result

    @property
    def days_in_month(self):
        """تعداد روزهای واقعی این ماه شمسی (۲۹/۳۰/۳۱) — پایه‌ی محاسبه‌ی حقوق ساعتی/روزانه‌ی همین ماه"""
        return days_in_jalali_month(self.jalali_year, self.jalali_month)

    @property
    def standard_monthly_hours_this_month(self):
        """ساعت استاندارد ماهانه، متناسب با تعداد روزهای واقعی همین ماه (نه فرض ثابت ۲۲۰ ساعت) —
        این دقیقاً همون چیزیه که باعث می‌شه ماه ۳۰ و ۳۱ روزه به‌صورت خودکار در محاسبات لحاظ بشه."""
        return round(self.days_in_month * STANDARD_DAILY_HOURS, 2)

    @property
    def hourly_wage(self):
        hours = self.standard_monthly_hours_this_month
        return round(self.gross_base_monthly / hours) if self.gross_base_monthly and hours else 0

    @property
    def daily_wage(self):
        return round(self.gross_base_monthly / self.days_in_month) if self.gross_base_monthly else 0

    @property
    def insurance_base_30days(self):
        """مزد مبنای بیمه‌ی ۳۰روزه، بر اساس وضعیت تاهل کارمند (از EmployeeProfile)"""
        sp = self._salary_profile
        if not sp:
            return 0
        try:
            marital = self.user.employee_profile.marital_status
        except Exception:
            marital = ''
        return sp.insurance_base_married if marital == 'married' else sp.insurance_base_single

    @property
    def insurance_amount(self):
        """حق بیمه‌ی سهم کارمند این ماه = ۷٪ از (مزد مبنای بیمه‌ی متناسب با تاهل/تجرد، پرورده‌شده به تعداد روزهای بیمه‌ی این ماه)"""
        base30 = self.insurance_base_30days
        if not base30:
            return 0
        prorated_base = base30 / 30 * self.insurance_days
        return round(prorated_base * EMPLOYEE_INSURANCE_RATE)

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
    def approved_leave_days_this_month(self):
        """تعداد روزهای مرخصی روزانه‌ی تاییدشده در همین ماه شمسی — خودکار از بخش مرخصی‌ها استخراج می‌شود.
        این روزها جزو ساعات کاری حساب می‌شوند (کسر نمی‌شوند)."""
        total = 0
        for r in self.user.leave_requests.filter(status='approved', leave_type='daily'):
            jd = jdatetime.date.fromgregorian(date=r.start_date)
            if jd.year == self.jalali_year and jd.month == self.jalali_month:
                total += r.days_count
        return total

    @property
    def approved_leave_hours_this_month(self):
        """جمع مرخصی ساعتی تاییدشده در همین ماه — این هم جزو ساعات کاری حساب می‌شود."""
        total = 0
        for r in self.user.leave_requests.filter(status='approved', leave_type='hourly'):
            jd = jdatetime.date.fromgregorian(date=r.start_date)
            if jd.year == self.jalali_year and jd.month == self.jalali_month:
                total += float(r.hours or 0)
        return total

    @property
    def gross_pay(self):
        """حقوق ناخالص = (حقوق ساعتی × ساعت کارکرد) + اضافه‌کاری + پاداش + اضافه‌پرداخت"""
        base = round(self.hourly_wage * float(self.worked_hours))
        return base + self.overtime_pay + self.bonus_amount + self.extra_payment

    @property
    def total_deductions(self):
        return self.insurance_amount + self.absence_deduction + self.undertime_deduction

    @property
    def net_pay(self):
        """حقوق خالص = ناخالص - (حق بیمه + کسر غیبت + کسر کم‌کاری)"""
        return max(0, self.gross_pay - self.total_deductions)

    @property
    def net_pay_words(self):
        """حقوق خالص به حروف فارسی (برای پایین فیش حقوقی)"""
        return number_to_persian_words(self.net_pay) + ' تومان'

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


class AttendanceLog(models.Model):
    """
    ثبت ساعت ورود و خروج روزانه‌ی هر کارمند. ثبت ورود/خروج توسط خودِ کارمند از دکمه‌های سبز/قرمز
    داشبورد انجام می‌شود و هرکدام فقط یک‌بار در روز قابل ثبت است (غیرقابل‌ویرایش توسط خودِ کارمند)؛
    فقط مدیر می‌تواند تاریخ/ساعت را دستی اصلاح کند.
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='attendance_logs')
    date = models.DateField(help_text='تاریخ (میلادی ذخیره می‌شود) — روزی که این ثبت مربوط به آن است')
    check_in = models.DateTimeField(null=True, blank=True)
    check_out = models.DateTimeField(null=True, blank=True)
    edited_by_admin = models.BooleanField(default=False, help_text='اگر مدیر دستی این رکورد را اصلاح کرده باشد True می‌شود')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'date'], name='unique_attendance_per_user_day')]
        ordering = ['-date']

    @property
    def date_jalali(self):
        return jdatetime.date.fromgregorian(date=self.date).strftime('%Y/%m/%d')

    @property
    def check_in_time_jalali(self):
        if not self.check_in:
            return None
        return jdatetime.datetime.fromgregorian(datetime=timezone.localtime(self.check_in)).strftime('%H:%M')

    @property
    def check_out_time_jalali(self):
        if not self.check_out:
            return None
        return jdatetime.datetime.fromgregorian(datetime=timezone.localtime(self.check_out)).strftime('%H:%M')

    @property
    def worked_hours(self):
        if self.check_in and self.check_out and self.check_out > self.check_in:
            delta = self.check_out - self.check_in
            return round(delta.total_seconds() / 3600, 2)
        return 0.0

    def __str__(self):
        return f"حضور {self.user.get_full_name()} — {self.date_jalali}"


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
