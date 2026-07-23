from django.db import models
from django.utils import timezone
from accounts.models import User
import jdatetime


def _jalali(dt):
    if not dt:
        return None
    local_dt = timezone.localtime(dt)
    return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')


class NewLead(models.Model):
    """لیست انتظار ورودی‌های جدید — سرنخ‌های تازه که هنوز مشخص نیست ثبت‌نام می‌کنند یا نه"""

    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار پیگیری'
        REGISTERED = 'registered', 'ثبت‌نام شد'
        CANCELLED = 'cancelled', 'کنسل شد'

    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    father_name = models.CharField(max_length=150, blank=True)
    national_code = models.CharField(max_length=20, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    phone = models.CharField(max_length=20)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    followup1_at = models.DateTimeField(null=True, blank=True)
    followup1_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    followup2_at = models.DateTimeField(null=True, blank=True)
    followup2_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    registered_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    deposit_amount = models.PositiveIntegerField(null=True, blank=True, help_text='مبلغ بیعانه (تومان)')
    deposit_paid_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def created_at_jalali(self):
        return _jalali(self.created_at)

    @property
    def birth_date_jalali(self):
        if not self.birth_date:
            return None
        return jdatetime.date.fromgregorian(date=self.birth_date).strftime('%Y/%m/%d')

    @property
    def followup1_at_jalali(self):
        return _jalali(self.followup1_at)

    @property
    def followup2_at_jalali(self):
        return _jalali(self.followup2_at)

    @property
    def registered_at_jalali(self):
        return _jalali(self.registered_at)

    @property
    def cancelled_at_jalali(self):
        return _jalali(self.cancelled_at)

    @property
    def deposit_paid_at_jalali(self):
        return _jalali(self.deposit_paid_at)

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.get_status_display()})"


class UnregisteredStudent(models.Model):
    """زبان‌آموزی که استادی معرفی کرده ولی هنوز ثبت‌نام نکرده — نیازمند پیگیری آموزشگاه"""

    class Status(models.TextChoices):
        TRACKING = 'tracking', 'در حال پیگیری'
        REGISTERED = 'registered', 'ثبت‌نام شد'

    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    class_level = models.CharField(max_length=50)
    national_code = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    tuition_price = models.PositiveIntegerField(null=True, blank=True, help_text='قیمت شهریه‌ی پیشنهادی')

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.TRACKING)
    registered_at = models.DateTimeField(null=True, blank=True)

    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_unregistered_students')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def created_at_jalali(self):
        return _jalali(self.created_at)

    @property
    def registered_at_jalali(self):
        return _jalali(self.registered_at)

    @property
    def followup_count(self):
        return self.followups.count()

    @property
    def last_followup_at_jalali(self):
        last = self.followups.order_by('-followed_up_at').first()
        return _jalali(last.followed_up_at) if last else None

    def __str__(self):
        return f"{self.first_name} {self.last_name} — {self.class_level}"


class UnregisteredStudentFollowup(models.Model):
    """هر بار که کسی روی «پیگیری» برای یک زبان‌آموز ثبت‌نام‌نشده می‌زند، یک ردیف اینجا ثبت می‌شود — بدون محدودیت تعداد"""
    student = models.ForeignKey(UnregisteredStudent, on_delete=models.CASCADE, related_name='followups')
    followed_up_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    followed_up_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-followed_up_at']

    @property
    def followed_up_at_jalali(self):
        return _jalali(self.followed_up_at)


class Debtor(models.Model):
    """بدهکاران — افرادی که مبلغی به آموزشگاه بدهکارند و باید پیگیری/تسویه شوند"""

    class Status(models.TextChoices):
        PENDING = 'pending', 'در حال پیگیری'
        SETTLED = 'settled', 'تسویه شد'

    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    phone = models.CharField(max_length=20)
    class_level = models.CharField(max_length=50, blank=True)
    debt_amount = models.PositiveIntegerField()
    description = models.TextField(blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    settled_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def created_at_jalali(self):
        return _jalali(self.created_at)

    @property
    def settled_at_jalali(self):
        return _jalali(self.settled_at)

    @property
    def followup_count(self):
        return self.followups.count()

    @property
    def last_followup_at_jalali(self):
        last = self.followups.order_by('-followed_up_at').first()
        return _jalali(last.followed_up_at) if last else None

    def __str__(self):
        return f"{self.first_name} {self.last_name} — {self.debt_amount} تومان"


class DebtorFollowup(models.Model):
    """هر بار پیگیری بدهکار — بدون محدودیت تعداد"""
    debtor = models.ForeignKey(Debtor, on_delete=models.CASCADE, related_name='followups')
    followed_up_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    followed_up_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-followed_up_at']

    @property
    def followed_up_at_jalali(self):
        return _jalali(self.followed_up_at)


class DiscountedPerson(models.Model):
    """آرشیو افراد دارای تخفیف — نام، کد ملی، درصد و علت تخفیف، و تاریخ پایان اعتبار تخفیف"""

    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)
    national_code = models.CharField(max_length=20, blank=True)
    discount_percent = models.PositiveIntegerField(help_text='درصد تخفیف (۰ تا ۱۰۰)')
    reason = models.CharField(max_length=255, blank=True, help_text='علت تخفیف')
    valid_until = models.DateField(null=True, blank=True, help_text='پایان اعتبار تخفیف')

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def created_at_jalali(self):
        return _jalali(self.created_at)

    @property
    def valid_until_jalali(self):
        if not self.valid_until:
            return None
        jd = jdatetime.date.fromgregorian(date=self.valid_until)
        return jd.strftime('%Y/%m/%d')

    @property
    def is_expired(self):
        if not self.valid_until:
            return False
        return self.valid_until < timezone.localdate()

    def __str__(self):
        return f"{self.first_name} {self.last_name} — {self.discount_percent}%"
