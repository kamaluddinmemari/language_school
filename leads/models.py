from django.db import models
from django.utils import timezone
from accounts.models import User
import jdatetime


def _jalali(dt):
    if not dt:
        return None
    local_dt = timezone.localtime(dt)
    return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')


def build_person_key(national_code, phone, first_name, last_name):
    national = ''.join(str(national_code or '').split()).strip()
    if national:
        return f'national:{national}'
    phone_value = ''.join(str(phone or '').split()).strip()
    name = ' '.join(f"{first_name or ''} {last_name or ''}".split()).casefold()
    return f'phone:{phone_value}|name:{name}' if phone_value else f'name:{name}'


def build_identity_key(national_code, phone, first_name, last_name, level=''):
    person = build_person_key(national_code, phone, first_name, last_name)
    normalized_level = ' '.join(str(level or '').split()).casefold()
    return f'{person}|level:{normalized_level}' if normalized_level else person


def get_current_term():
    """
    ترمی که تاریخ امروز داخل بازه‌ی start_date/end_date آن است؛ اگر هیچ ترمی امروز را
    پوشش نمی‌دهد (مثلاً بین دو ترم)، جدیدترین ترم (بر اساس سال و شماره‌ترم) برگردانده
    می‌شود. اگر اصلاً ترمی تعریف نشده باشد، None.
    """
    from class_management.models import Term
    today = timezone.localdate()
    current = Term.objects.filter(start_date__lte=today, end_date__gte=today).first()
    if current:
        return current
    return sorted(Term.objects.all(), key=lambda t: (t.year, t.term_number))[-1] if Term.objects.exists() else None


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
    term = models.ForeignKey('class_management.Term', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    identity_key = models.CharField(max_length=255, blank=True, default='', editable=False)

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
        constraints = [models.UniqueConstraint(
            fields=['term', 'identity_key'],
            condition=models.Q(term__isnull=False) & ~models.Q(identity_key=''),
            name='uniq_newlead_term_identity',
        )]

    def save(self, *args, **kwargs):
        self.identity_key = build_identity_key(self.national_code, self.phone, self.first_name, self.last_name)
        super().save(*args, **kwargs)

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

    @property
    def term_title(self):
        return self.term.title if self.term else None

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
    identity_key = models.CharField(max_length=255, blank=True, default='', editable=False)
    tuition_price = models.PositiveIntegerField(null=True, blank=True, help_text='قیمت شهریه‌ی پیشنهادی')

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.TRACKING)
    registered_at = models.DateTimeField(null=True, blank=True)
    term = models.ForeignKey(
        'class_management.Term', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        help_text='ترمی که این فرد در آن ثبت شده — برای فیلتر ترمی در صفحه‌ی پیگیری',
    )

    submitted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_unregistered_students')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(
            fields=['term', 'identity_key'],
            condition=models.Q(term__isnull=False) & ~models.Q(identity_key=''),
            name='uniq_unregistered_term_identity',
        )]

    def save(self, *args, **kwargs):
        self.identity_key = build_identity_key(self.national_code, self.phone, self.first_name, self.last_name, self.class_level)
        super().save(*args, **kwargs)

    @property
    def latest_level(self):
        person_key = build_person_key(self.national_code, self.phone, self.first_name, self.last_name)
        return type(self).objects.filter(
            term=self.term,
            identity_key__startswith=person_key + '|level:',
        ).order_by('-created_at', '-id').values_list('class_level', flat=True).first() or self.class_level

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

    @property
    def term_title(self):
        return self.term.title if self.term else None

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
    identity_key = models.CharField(max_length=255, blank=True, default='', editable=False)
    class_level = models.CharField(max_length=50, blank=True)
    debt_amount = models.PositiveIntegerField()
    description = models.TextField(blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    settled_at = models.DateTimeField(null=True, blank=True)
    term = models.ForeignKey(
        'class_management.Term', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
        help_text='ترمی که این فرد در آن ثبت شده — برای فیلتر ترمی در صفحه‌ی پیگیری',
    )

    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(
            fields=['term', 'identity_key'],
            condition=models.Q(term__isnull=False) & ~models.Q(identity_key=''),
            name='uniq_debtor_term_identity',
        )]

    def save(self, *args, **kwargs):
        self.identity_key = build_identity_key('', self.phone, self.first_name, self.last_name)
        super().save(*args, **kwargs)

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

    @property
    def term_title(self):
        return self.term.title if self.term else None

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


class DropoutFollowup(models.Model):
    """پیگیری نامحدود دانش‌آموزی که از یک ترم به ترم بعد ثبت‌نام نکرده است."""
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='dropout_followups')
    from_term = models.ForeignKey('class_management.Term', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    to_term = models.ForeignKey('class_management.Term', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    followed_up_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    followed_up_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ['-followed_up_at']

    @property
    def followed_up_at_jalali(self):
        return _jalali(self.followed_up_at)

    @property
    def followed_up_by_name(self):
        return self.followed_up_by.get_full_name() if self.followed_up_by else ''
