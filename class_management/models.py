from django.db import models
from django.conf import settings
from django.utils import timezone
import jdatetime
from level_tests.levels import get_all_level_choices
from level_tests.models import LevelTest


import re


# تشخیص خودکار گروه سنی از روی خودِ کد سطح — چون هر سطح فقط متعلق به یک گروه سنی است:
# کودک: e1..e5 / i1..i5   |   نوجوان: preteen, teen1..teen15   |   بزرگسال: کدهای عددی ۱۰۱ تا ۶۰۶
# قبلاً گروه سنی از روی آخرین آزمون تعیین‌سطح دانش‌آموز حدس زده می‌شد که باعث خطای
# «شهریه‌ای تعریف نشده» می‌شد (چون ممکن بود آزمونی برای دانش‌آموز ثبت نشده باشد).
def infer_age_group_from_level(level):
    """
    گروه سنیِ یک سطح را برمی‌گرداند — مستقیم از جدول مرجع StandardLevel (اپ level_tests)،
    نه با حدسِ الگوی رشته. این یعنی هر سطحی که از بخش «تعریف سطوح استاندارد» اضافه بشه
    (even با شکل غیرمعمول)، همه‌جا بلافاصله و درست شناسایی می‌شه.
    """
    if not level:
        return ''
    from level_tests.models import StandardLevel
    lvl = str(level).strip()
    match = StandardLevel.objects.filter(code__iexact=lvl).first()
    return match.age_group if match else ''


def _jalali(dt):
    if not dt:
        return None
    local_dt = timezone.localtime(dt)
    return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')


MORNING_TIME_SLOTS = ['08:00-09:30', '09:45-11:15', '11:30-13:00']
EVENING_TIME_SLOTS = ['15:45-17:15', '17:30-19:00', '19:00-20:30']
EVENING_LATE_TIME_SLOTS = ['17:30-19:00', '19:00-20:30']  # برای زبان‌آموزان چرخشی — بعد از ۱۷:۳۰
# ساعت‌های واقعی روزهای زوج/فرد (سه روز در هفته) — بدون ۰۸:۰۰-۰۹:۳۰ که فقط برای پنجشنبه‌صبح است
THREE_DAY_TIME_SLOTS = ['09:45-11:15', '11:30-13:00', '15:45-17:15', '17:30-19:00', '19:00-20:30']
THURSDAY_MORNING_SLOT = '08:00-13:00'
THURSDAY_EVENING_SLOT = '13:00-17:15'
FRIDAY_SLOT = '08:30-13:15'

ALL_STANDARD_TIME_SLOTS = MORNING_TIME_SLOTS + EVENING_TIME_SLOTS + [THURSDAY_MORNING_SLOT, THURSDAY_EVENING_SLOT, FRIDAY_SLOT]


class Term(models.Model):
    """
    ترم تحصیلی — هر سال شمسی معمولاً ۸ ترم دارد. با تعریف هر ترم (سال + شماره‌ترم ۱ تا ۸ +
    بازه‌ی تاریخ شروع/پایان)، کلاس‌های فیزیکی که با «ساخت کلاس فیزیکی» ساخته می‌شوند به همان
    ترم وصل می‌شوند — یعنی هر ترم مجموعه‌ی کامل و مستقل خودش از کلاس‌ها را دارد (خواسته‌ی
    «انتخاب ترم» در بخش مدیریت کلاس‌ها).
    """
    year = models.PositiveIntegerField(help_text='سال شمسی، مثلاً ۱۴۰۵')
    term_number = models.PositiveSmallIntegerField(help_text='شماره‌ی ترم، از ۱ تا ۸')
    start_date = models.DateField(help_text='تاریخ شروع ترم (میلادی ذخیره می‌شود؛ در پنل به‌صورت شمسی وارد/نمایش می‌شود)')
    end_date = models.DateField(help_text='تاریخ پایان ترم (میلادی ذخیره می‌شود؛ در پنل به‌صورت شمسی وارد/نمایش می‌شود)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-year', 'term_number']
        constraints = [
            models.UniqueConstraint(fields=['year', 'term_number'], name='unique_term_per_year')
        ]

    @property
    def start_date_jalali(self):
        if not self.start_date:
            return None
        return jdatetime.date.fromgregorian(date=self.start_date).strftime('%Y/%m/%d')

    @property
    def end_date_jalali(self):
        if not self.end_date:
            return None
        return jdatetime.date.fromgregorian(date=self.end_date).strftime('%Y/%m/%d')

    @property
    def title(self):
        return f"ترم {self.term_number} سال {self.year}"

    def __str__(self):
        return self.title


class ClassSlot(models.Model):
    """
    یک کلاس، که مدیر یکی‌یکی وارد می‌کند — با روز/نوع برگزاری هفتگی، ساعت جاری (از لیست
    استاندارد)، ظرفیت، و توضیحات آزاد (مثلاً محدودیت جابجایی بین کلاس‌های خاص). وضعیت
    چرخشی/فقط‌صبح بودن دیگر خاصیت خودِ کلاس نیست — خاصیت هر «سطح» است و موقع تخصیص پرسیده
    می‌شود (بخش «افزودن سطح» در تخصیص). حذف/ویرایش هر کلاس در هر لحظه آزاد است.
    """

    class DayType(models.TextChoices):
        EVEN = 'even', 'روز زوج (سه روز در هفته)'
        ODD = 'odd', 'روز فرد (سه روز در هفته)'
        THURSDAY_MORNING = 'thursday_morning', 'یک روز در هفته - پنجشنبه صبح'
        THURSDAY_EVENING = 'thursday_evening', 'یک روز در هفته - پنجشنبه عصر'
        FRIDAY = 'friday', 'یک روز در هفته - جمعه'
        ONLINE = 'online', 'آنلاین'
        HYBRID = 'hybrid', 'ترکیبی (آنلاین و حضوری)'

    class Gender(models.TextChoices):
        GIRLS = 'girls', 'دخترانه'
        BOYS = 'boys', 'پسرانه'
        MIXED = 'mixed', 'مختلط'

    number = models.PositiveIntegerField(help_text='شماره کلاس — همان شماره می‌تواند در چند ساعت/روز مختلف تکرار شود (مثلاً کلاس ۱ هم صبح هم عصر)')
    term = models.ForeignKey(
        Term, on_delete=models.SET_NULL, null=True, blank=True, related_name='class_slots',
        help_text='ترمی که این کلاس در آن ساخته شده — کلاس‌های قدیمی‌تر از قبل از این قابلیت می‌توانند خالی (بدون ترم) بمانند'
    )
    title = models.CharField(max_length=100, blank=True)
    day_type = models.CharField(max_length=20, choices=DayType.choices)
    time_slot = models.CharField(max_length=20, blank=True, help_text='ساعت جاری کلاس — ترجیحاً از لیست استاندارد')
    gender = models.CharField(max_length=10, choices=Gender.choices, default=Gender.MIXED, help_text='دخترانه/پسرانه/مختلط — برای جایگذاری صحیح دانش‌آموزان')
    is_online = models.BooleanField(default=False, help_text='کلاس آنلاین است — دقیقاً همان قواعد تشکیل/ثبت‌نام کلاس‌های ترمیک حضوری را دارد، فقط با لینک ورود آنلاین')
    meeting_link = models.URLField(max_length=500, blank=True, help_text='لینک کلاس آنلاین (مثلاً Google Meet/Zoom) — بعد از تایید ثبت‌نام، هم به استاد هم به دانش‌آموز در اپ نمایش داده می‌شود')
    notes = models.TextField(blank=True, help_text='توضیحات آزاد، مثلاً «این کلاس فقط بین کلاس ۱ و ۹ جابجا شود»')

    capacity = models.PositiveIntegerField(default=10)
    teacher_name = models.CharField(max_length=150, blank=True)

    assigned_level = models.CharField(max_length=50, blank=True)
    current_count = models.PositiveIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['number']
        constraints = [
            models.UniqueConstraint(
                fields=['number', 'day_type', 'time_slot', 'term', 'is_online'],
                name='unique_class_number_per_day_time_term_mode',
                violation_error_message='این شماره کلاس دقیقاً در همین روز، ساعت، ترم و حالت (آنلاین/حضوری) از قبل وجود دارد',
            )
        ]

    @property
    def day_type_display(self):
        return self.get_day_type_display()

    @property
    def is_three_day(self):
        return self.day_type in (self.DayType.EVEN, self.DayType.ODD)

    @property
    def capacity_status(self):
        """'empty' (سفید) | 'ok' (سبز، جا دارد) | 'full' | 'over' (قرمز، پر/بیش از ظرفیت)"""
        if self.current_count == 0:
            return 'empty'
        if self.current_count < self.capacity:
            return 'ok'
        if self.current_count == self.capacity:
            return 'full'
        return 'over'

    @property
    def seats_left(self):
        return self.capacity - self.current_count

    @property
    def surplus(self):
        return max(0, self.current_count - self.capacity)

    @property
    def real_enrolled_count(self):
        """
        تعداد واقعیِ دانش‌آموزهای تک‌به‌تک ثبت‌نام‌شده (از روی خودِ ردیف‌های ClassSlotEnrollment)
        — برخلاف current_count که فقط عدد انتزاعیِ «تخصیص خودکار» است. ثبت‌نام‌های خودِ دانش‌آموز
        از اپ که هنوز رسیدشان توسط مدیر تایید نشده (payment_verified=False) جزو این عدد حساب
        نمی‌شوند — یعنی تا تایید نشوند، اصلاً «توی کلاس» به‌حساب نمی‌آیند (خواسته‌ی ۱)
        """
        return self.enrollments.filter(payment_verified=True).count()

    @property
    def real_capacity_status(self):
        """'empty' | 'ok' (سبز) | 'full' | 'over' (قرمز) — بر اساس ثبت‌نام واقعی، نه عدد تخصیص"""
        n = self.real_enrolled_count
        if n == 0:
            return 'empty'
        if n < self.capacity:
            return 'ok'
        if n == self.capacity:
            return 'full'
        return 'over'

    @property
    def real_seats_left(self):
        return self.capacity - self.real_enrolled_count

    @property
    def real_surplus(self):
        return max(0, self.real_enrolled_count - self.capacity)

    @property
    def updated_at_jalali(self):
        return _jalali(self.updated_at)

    def fixed_time_slot(self):
        """ساعت ثابت برای فرمت‌های تک‌روزه — این‌ها نیازی به انتخاب دستی ساعت ندارند"""
        return {
            self.DayType.THURSDAY_MORNING: THURSDAY_MORNING_SLOT,
            self.DayType.THURSDAY_EVENING: THURSDAY_EVENING_SLOT,
            self.DayType.FRIDAY: FRIDAY_SLOT,
        }.get(self.day_type)

    def time_category(self):
        """
        دسته‌ی ساعتی کلاس بر اساس ساعت فعلی‌اش (نه روزش) — برای تطبیق با نیاز سطح‌ها در تخصیص.
        فقط برای کلاس‌های زوج/فرد/آنلاین/ترکیبی معنی دارد (پنجشنبه/جمعه جدا و بر اساس day_type مدیریت می‌شوند).
        """
        if not self.time_slot or '-' not in self.time_slot:
            return set()
        start = self.time_slot.split('-')[0]
        if start in ('17:30', '19:00'):
            return {'evening_late', 'evening_any'}
        if start == '15:45':
            return {'evening_any'}
        if start in ('08:00', '09:45', '11:30'):
            return {'morning'}
        return set()

    def save(self, *args, **kwargs):
        fixed = self.fixed_time_slot()
        if fixed:
            self.time_slot = fixed
        super().save(*args, **kwargs)

    def __str__(self):
        return f"کلاس {self.number} — {self.get_day_type_display()} ({self.time_slot or 'ساعت نامشخص'})"


class ClassSlotEnrollment(models.Model):
    """
    ثبت‌نام واقعیِ یک دانش‌آموز مشخص (با کد ملی) توی یک کلاس فیزیکی خاص — برخلاف
    current_count روی خودِ ClassSlot (که فقط یه عدد خامه، برای تخصیص انتزاعیِ سطح‌ها)،
    این مدل واقعاً کدام دانش‌آموز کجاست را نگه می‌دارد تا بشود لیست حضور و غیاب ساخت.
    """
    class PaymentMethod(models.TextChoices):
        POS = 'pos', 'دستگاه کارت‌خوان (پوز)'
        CASH = 'cash', 'نقدی'
        GATEWAY = 'gateway', 'درگاه پرداخت آنلاین'
        CARD_TO_CARD = 'card_to_card', 'کارت به کارت'
        WALLET = 'wallet', 'کیف پول'

    class_slot = models.ForeignKey(ClassSlot, on_delete=models.CASCADE, related_name='enrollments')
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='class_slot_enrollments')
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    tuition_amount = models.PositiveIntegerField(default=0, help_text='مبلغ شهریه‌ی پرداختی (تومان)')
    discount_percent = models.PositiveIntegerField(default=0, help_text='درصد تخفیفی که موقع این ثبت‌نام اعمال شد (اگر داشته باشد)')
    pos_reference_code = models.CharField(max_length=50, blank=True, help_text='کد ساعت/شماره پیگیری دستگاه پوز — فقط وقتی پرداخت از طریق پوز باشد')
    receipt_image = models.ImageField(upload_to='enrollment_receipts/', null=True, blank=True, help_text='تصویر رسید کارت‌به‌کارت — فقط برای ثبت‌نامِ خودِ دانش‌آموز از طریق اپ')
    self_enrolled = models.BooleanField(default=False, help_text='True یعنی خودِ دانش‌آموز از طریق اپ ثبت‌نام کرده، نه مدیر')
    payment_verified = models.BooleanField(default=True, help_text='ثبت‌نام‌های دستیِ مدیر همیشه تاییدشده‌اند؛ ثبت‌نام خودِ دانش‌آموز (کارت‌به‌کارت) تا بررسی رسید توسط مدیر، False می‌ماند')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        constraints = [
            models.UniqueConstraint(fields=['class_slot', 'student'], name='unique_student_per_class_slot')
        ]

    @property
    def created_at_jalali(self):
        return _jalali(self.created_at)

    def __str__(self):
        return f"{self.student.get_full_name()} — کلاس {self.class_slot.number}"


class TuitionSetting(models.Model):
    """
    شهریه‌ی مصوب هر سطح به تفکیک گروه سنی (کودک/نوجوان/بزرگسال) — همان گروه‌بندی سنی‌ای که در
    اپ level_tests استفاده می‌شود. موقع ثبت‌نام، با توجه به سطحِ کلاس و گروه سنی دانش‌آموز
    (از روی آخرین آزمون تعیین‌سطحِ تکمیل‌شده‌اش)، این مبلغ به‌عنوان پیش‌فرض پیشنهاد می‌شود.
    """
    level = models.CharField(max_length=10, choices=get_all_level_choices)
    age_group = models.CharField(max_length=10, choices=LevelTest.AgeGroup.choices)
    amount = models.PositiveIntegerField(default=0, help_text='شهریه‌ی مصوب (تومان)')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['level', 'age_group']
        constraints = [
            models.UniqueConstraint(fields=['level', 'age_group'], name='unique_tuition_per_level_age_group')
        ]

    @property
    def level_display(self):
        return dict(get_all_level_choices()).get(self.level, self.level)

    @property
    def age_group_display(self):
        return self.get_age_group_display()

    @property
    def updated_at_jalali(self):
        return _jalali(self.updated_at)

    def __str__(self):
        return f"{self.level} / {self.get_age_group_display()}: {self.amount}"


class DiscountedPerson(models.Model):
    """
    لیست «افراد دارای تخفیف» — با هر ثبت‌نامی که درصد تخفیف صفر نباشد، خودکار ساخته یا (اگر از
    قبل برای همان دانش‌آموز وجود داشت) به‌روزرسانی می‌شود.
    """
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='discount_records')
    discount_percent = models.PositiveIntegerField(default=0)
    class_slot = models.ForeignKey(ClassSlot, on_delete=models.SET_NULL, null=True, blank=True, related_name='discount_records')
    approved_tuition = models.PositiveIntegerField(default=0, help_text='مبلغ نهایی شهریه بعد از تخفیف، در آخرین ثبت‌نامِ دارای تخفیف')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    @property
    def updated_at_jalali(self):
        return _jalali(self.updated_at)

    def __str__(self):
        return f"{self.student.get_full_name()} — {self.discount_percent}%"


class EnrollmentRefund(models.Model):
    """رکورد استرداد شهریه — با زدن دکمه‌ی «استرداد» روی یک دانش‌آموزِ ثبت‌نام‌شده ساخته می‌شود"""
    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='refunds')
    class_slot = models.ForeignKey(ClassSlot, on_delete=models.SET_NULL, null=True, blank=True, related_name='refunds')
    amount = models.PositiveIntegerField(default=0)
    card_number = models.CharField(max_length=30)
    receiver_name = models.CharField(max_length=150)
    refunded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='refunds_processed')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def created_at_jalali(self):
        return _jalali(self.created_at)

    def __str__(self):
        return f"استرداد {self.amount} — {self.student.get_full_name()}"


class WalletTransaction(models.Model):
    """تاریخچه‌ی واریز/برداشت کیف پول دانش‌آموز — برای پیگیری و شفافیت مالی"""

    class Kind(models.TextChoices):
        CREDIT = 'credit', 'واریز به کیف پول'
        DEBIT = 'debit', 'برداشت از کیف پول'

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet_transactions')
    kind = models.CharField(max_length=10, choices=Kind.choices)
    amount = models.PositiveIntegerField()
    reason = models.CharField(max_length=255, blank=True)
    class_slot = models.ForeignKey(ClassSlot, on_delete=models.SET_NULL, null=True, blank=True, related_name='wallet_transactions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def created_at_jalali(self):
        return _jalali(self.created_at)


class LevelRenewalApproval(models.Model):
    """
    وقتی بیش از ۶۰ روز از آخرین ثبت‌نام/تعیین‌سطح دانش‌آموز گذشته، برای ادامه‌ی ثبت‌نام یا
    باید تعیین‌سطح مجدد بشه یا مدیر آموزش سطح فعلی رو بدون تعیین‌سطح تازه تایید کنه.
    """
    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار بررسی'
        APPROVED = 'approved', 'تاییدشده'
        REJECTED = 'rejected', 'ردشده'

    student = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='level_renewal_requests')
    level = models.CharField(max_length=10)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='level_renewals_requested')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='level_renewals_reviewed')
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def created_at_jalali(self):
        return _jalali(self.created_at)

    @property
    def reviewed_at_jalali(self):
        return _jalali(self.reviewed_at)

    def __str__(self):
        return f"{self.student.get_full_name()} — {self.level} — {self.get_status_display()}"


    def __str__(self):
        return f"{self.get_kind_display()} {self.amount} — {self.student.get_full_name()}"
