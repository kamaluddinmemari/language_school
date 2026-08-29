from django.db import models
from django.utils import timezone
from accounts.models import User, persian_only_validator
from .levels import get_all_level_choices
import jdatetime


class StandardLevel(models.Model):
    """
    سطح استاندارد قابل تعریف از پنل («تعریف سطوح استاندارد») — منبع واحد و مرجع همه‌جای
    پروژه: تعیین‌سطح، تعریف کلاس، ثبت‌نام، تعریف شهریه، پروفایل دانش‌آموز. با افزودن/حذف
    سطح از این جدول، همه‌جا خودکار به‌روز می‌شود (چون choices همه‌ی فیلدهای مرتبط از
    get_all_level_choices() که این جدول را می‌خواند تغذیه می‌شود، نه از لیست ثابت).
    """
    class AgeGroup(models.TextChoices):
        KIDS = 'kids', 'کودک'
        TEEN = 'teen', 'نوجوان'
        ADULT = 'adult', 'بزرگسال'

    code = models.CharField(max_length=20, unique=True, help_text='کد سطح، مثلاً E1 یا Teen3 یا 305')
    age_group = models.CharField(max_length=10, choices=AgeGroup.choices)
    order = models.PositiveIntegerField(default=0, help_text='ترتیب نمایش داخل گروه سنی — همان ترتیب استاندارد پیشرفت سطح')
    is_terminal = models.BooleanField(default=False, help_text='سطح پایانی این رده — بعد از این سطح دانش‌آموز برای ترم بعد نیازمند تعیین سطح مجدد است. فقط یک سطح پایانی در هر رده معتبر است.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['age_group', 'order', 'code']

    def __str__(self):
        return f"{self.code} ({self.get_age_group_display()})"


class LevelTestPriceSetting(models.Model):
    """تنظیمات قیمت پیش‌فرض آزمون تعیین سطح — سینگلتون (فقط آخرین ردیف در نظر گرفته می‌شود)"""
    price = models.PositiveIntegerField(default=0, help_text='قیمت پیش‌فرض هر آزمون تعیین سطح (تومان) — می‌تواند ۰/رایگان باشد')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"قیمت پیش‌فرض تعیین سطح: {self.price}"


class LevelTest(models.Model):
    """
    چرخه‌ی ارجاع تعیین سطح:
    ۱) مدیر/کانتر مشخصات اولیه‌ی داوطلب را در پنل ادمین وارد می‌کند (status=pending).
    ۲) رکورد خودکار در صف پنل محدود «مسئول آموزش» (نقش evaluator) ظاهر می‌شود.
    ۳) مسئول آموزش بعد از تعیین سطح، نتیجه (گروه سنی + سطح) را برمی‌گرداند (status=completed).
    ۴) پنل ادمین با رفرش خودکار، مشخصات اولیه + نتیجه را آنلاین می‌بیند.
    """

    class AgeGroup(models.TextChoices):
        KIDS = 'kids', 'کودک'
        TEEN = 'teen', 'نوجوان'
        ADULT = 'adult', 'بزرگسال'

    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار تعیین سطح'
        COMPLETED = 'completed', 'تعیین سطح شده'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'unpaid', 'پرداخت نشده'
        PAID = 'paid', 'پرداخت شده'

    class Mode(models.TextChoices):
        ONLINE = 'online', 'آنلاین'
        ONSITE = 'onsite', 'حضوری'

    class PaymentMethod(models.TextChoices):
        CARD_TO_CARD = 'card', 'کارت به کارت'
        GATEWAY = 'gateway', 'درگاه پرداخت'

    # مشخصات اولیه — فقط توسط مدیر/کانتر وارد می‌شود
    first_name = models.CharField(max_length=150, validators=[persian_only_validator])
    last_name = models.CharField(max_length=150, validators=[persian_only_validator])
    father_name = models.CharField(max_length=150, blank=True, validators=[persian_only_validator])
    birth_date = models.DateField(null=True, blank=True)
    national_code = models.CharField(max_length=10, blank=True)
    phone = models.CharField(max_length=11, blank=True)
    gender = models.CharField(max_length=10, choices=User.Gender.choices, blank=True, help_text='برای ساخت خودکار حساب دانش‌آموز وقتی تعیین‌سطح تکمیل می‌شود لازم است')
    # اگر این آزمون برای یک دانش‌آموزِ از‌قبل‌ثبت‌شده (مثلاً از «ثبت‌نام مستقیم») ساخته شده،
    # اینجا به حساب واقعی‌اش وصل می‌شود — تا نتیجه بعداً در لیست دانش‌آموزان هم قابل‌مشاهده/ویرایش باشد
    student = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='level_tests_as_student', limit_choices_to={'role': 'student'}
    )
    price = models.PositiveIntegerField(null=True, blank=True, help_text='قیمت این آزمون — پیش‌فرض از تنظیمات، ولی همیشه قابل ویرایش برای هر مورد')
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)

    # خواسته‌ی «دکمه‌ی درخواست وقت تعیین سطح» در اپ دانش‌آموز — این چهار فیلد فقط برای
    # درخواست‌هایی پر می‌شوند که خودِ دانش‌آموز (نه مدیر/کانتر) از اپ ثبت کرده باشد
    mode = models.CharField(max_length=10, choices=Mode.choices, blank=True, help_text='آنلاین/حضوری — انتخاب دانش‌آموز موقع درخواست از اپ')
    meeting_link = models.CharField(max_length=300, blank=True, help_text='لینک تعیین‌سطح آنلاین — مدیر بعد از هماهنگی وارد می‌کند و برای دانش‌آموز در اپ نمایش داده می‌شود')
    self_requested = models.BooleanField(default=False, help_text='آیا این رکورد را خودِ دانش‌آموز از اپ درخواست داده (نه مدیر/کانتر)')
    payment_method = models.CharField(max_length=10, choices=PaymentMethod.choices, blank=True)
    receipt_image = models.ImageField(upload_to='level_test_receipts/', null=True, blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)

    # نتیجه — فقط توسط مسئول آموزش (یا مدیر به‌جایش) پر می‌شود
    age_group = models.CharField(max_length=10, choices=AgeGroup.choices, blank=True)
    level = models.CharField(max_length=20, choices=get_all_level_choices, blank=True)
    test_date = models.DateTimeField(null=True, blank=True)
    evaluator = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='level_tests_conducted', limit_choices_to={'role': 'evaluator'}
    )
    evaluator_name = models.CharField(max_length=150, blank=True, help_text='برای وقتی ارزیاب حساب کاربری ندارد و مدیر به‌جایش وارد می‌کند')
    notes = models.TextField(blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='level_tests_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def birth_date_jalali(self):
        if not self.birth_date:
            return None
        return jdatetime.date.fromgregorian(date=self.birth_date).strftime('%Y/%m/%d')

    @property
    def age(self):
        """سن فعلی (به سال) — محاسبه‌ی خودکار از روی تاریخ تولد، برای نمایش در اپ استاد/ارزیاب"""
        if not self.birth_date:
            return None
        today = timezone.localdate()
        years = today.year - self.birth_date.year
        if (today.month, today.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years

    @property
    def test_date_jalali(self):
        if not self.test_date:
            return None
        local_dt = timezone.localtime(self.test_date)
        return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')

    @property
    def created_at_jalali(self):
        if not self.created_at:
            return None
        local_dt = timezone.localtime(self.created_at)
        return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')

    @property
    def display_evaluator_name(self):
        if self.evaluator:
            return f"{self.evaluator.first_name} {self.evaluator.last_name}"
        return self.evaluator_name

    def save(self, *args, **kwargs):
        if self.evaluator and not self.evaluator_name:
            self.evaluator_name = f"{self.evaluator.first_name} {self.evaluator.last_name}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.get_status_display()})"
