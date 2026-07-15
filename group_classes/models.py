from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator
from accounts.models import User
import jdatetime


class GroupPriceSetting(models.Model):
    """
    تنظیمات قیمت‌گذاری کلاس‌های گروهی/ورکشاپ — سینگلتون (فقط آخرین ردیف در نظر گرفته می‌شود)،
    کاملاً مستقل از PriceSetting فاز ۱ (کلاس خصوصی انفرادی).
    - ورکشاپ: قیمت هرنفر مستقیم روی خودِ GroupSession تعیین می‌شود (می‌تواند ۰/رایگان باشد)،
      این تنظیمات برایش استفاده نمی‌شود.
    - خصوصی گروهی: قیمت هرنفر پلکانی است — ۲ نفر یک نرخ، ۳ نفر و بیشتر نرخ دیگر.
    """
    price_for_two = models.PositiveIntegerField(default=0, help_text='قیمت هرنفر وقتی کلاس خصوصی گروهی دقیقاً ۲ نفره است')
    price_for_three_plus = models.PositiveIntegerField(default=0, help_text='قیمت هرنفر وقتی کلاس خصوصی گروهی ۳ نفر یا بیشتر است')
    teacher_share_percent = models.PositiveIntegerField(default=70)
    school_share_percent = models.PositiveIntegerField(default=30)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"تنظیمات قیمت گروهی (۲نفره: {self.price_for_two} — ۳+نفره: {self.price_for_three_plus})"


class GroupSession(models.Model):
    """
    یک «جلسه»/دوره‌ی گروهی که مدیر می‌سازد و چند نفر (از وب یا اپ) به آن ملحق می‌شوند.
    دو نوع: ورکشاپ (قیمت ثابت هرنفر، قابل ویرایش، می‌تواند رایگان باشد) و خصوصی گروهی
    (قیمت پلکانی بر اساس تعداد نهایی نفرات، از GroupPriceSetting خوانده می‌شود).
    چرخه‌ی وضعیت مثل فاز ۱ است: باز برای ثبت‌نام → ارجاع به استاد → تایید نهایی → مختومه.
    """

    class SessionType(models.TextChoices):
        WORKSHOP = 'workshop', 'ورکشاپ'
        PRIVATE_GROUP = 'private_group', 'خصوصی گروهی'

    class Status(models.TextChoices):
        OPEN = 'open', 'باز برای ثبت‌نام'
        ASSIGNING = 'assigning', 'ارجاع به استاد'
        CONFIRMED = 'confirmed', 'تایید نهایی'
        COMPLETED = 'completed', 'مختومه'
        REJECTED = 'rejected', 'رد شده'
        CANCELLED = 'cancelled', 'کنسل شده'

    class SessionDuration(models.TextChoices):
        ONE_HOUR = '1', 'یک ساعت'
        ONE_HALF = '1.5', 'یک و نیم ساعت'

    session_type = models.CharField(max_length=20, choices=SessionType.choices)
    title = models.CharField(max_length=200, blank=True, help_text='عنوان ورکشاپ (اختیاری). برای خصوصی گروهی خودکار ساخته می‌شود')
    language_level = models.CharField(max_length=50)
    class_date = models.DateTimeField(null=True, blank=True)
    session_duration = models.CharField(max_length=5, choices=SessionDuration.choices, default=SessionDuration.ONE_HALF)
    session_count = models.PositiveIntegerField(default=1)
    capacity = models.PositiveIntegerField(validators=[MinValueValidator(2)])
    price_per_person = models.PositiveIntegerField(null=True, blank=True, help_text='فقط برای ورکشاپ؛ می‌تواند ۰ (رایگان) باشد')
    price_per_session = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='قیمت هرنفر برای هر جلسه (اختیاری). اگر پر شود، قیمت کل هرنفر = این مقدار × تعداد جلسات'
    )
    teacher_share_percent_override = models.PositiveIntegerField(
        null=True, blank=True,
        help_text='درصد اختصاصی سهم استاد برای همین جلسه (اختیاری). اگر خالی باشد، از تنظیمات مشترک استفاده می‌شود'
    )

    assigned_teachers = models.ManyToManyField(User, blank=True, related_name='group_sessions_referred', limit_choices_to={'role__in': User.TEACHER_LIKE_ROLES})
    accepted_teachers = models.ManyToManyField(User, blank=True, related_name='group_sessions_accepted', limit_choices_to={'role__in': User.TEACHER_LIKE_ROLES})
    teacher = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='group_sessions_teaching', limit_choices_to={'role__in': User.TEACHER_LIKE_ROLES})

    status = models.CharField(max_length=15, choices=Status.choices, default=Status.OPEN)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='group_sessions_created')
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def created_at_jalali(self):
        if not self.created_at:
            return None
        local_dt = timezone.localtime(self.created_at)
        return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')

    @property
    def class_date_jalali(self):
        if not self.class_date:
            return None
        local_dt = timezone.localtime(self.class_date)
        return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')

    @property
    def completed_at_jalali(self):
        if not self.completed_at:
            return None
        local_dt = timezone.localtime(self.completed_at)
        return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')

    @property
    def participant_count(self):
        return self.participants.count()

    @property
    def seats_left(self):
        return max(self.capacity - self.participant_count, 0)

    def get_price_per_session_amount(self):
        """قیمت هرنفر برای یک جلسه — اگر تنظیم اختصاصی شده باشد همان، وگرنه قیمت کل هرنفر تقسیم بر تعداد جلسات"""
        if self.price_per_session is not None:
            return self.price_per_session
        if self.session_count:
            return int(round(self.get_price_per_person() / self.session_count))
        return self.get_price_per_person()

    def get_price_per_person(self):
        """
        قیمت نهایی هرنفر برای کل دوره.
        اگر `price_per_session` تنظیم شده باشد (قابلیت تنظیم مجزا برای هر ورکشاپ/کلاس گروهی)،
        قیمت کل = قیمت هر جلسه × تعداد جلسات. در غیر این صورت رفتار قبلی حفظ می‌شود:
        برای ورکشاپ مستقیم از خود جلسه، برای خصوصی گروهی پلکانی از تنظیمات مشترک.
        """
        if self.price_per_session is not None:
            return self.price_per_session * self.session_count
        if self.session_type == self.SessionType.WORKSHOP:
            return self.price_per_person or 0
        setting = GroupPriceSetting.objects.order_by('-updated_at').first()
        if not setting:
            return 0
        count = self.participant_count
        if count <= 2:
            return setting.price_for_two
        return setting.price_for_three_plus

    @property
    def total_price(self):
        return self.get_price_per_person() * self.participant_count

    @property
    def teacher_share_percent_effective(self):
        """درصد سهم استاد که واقعاً اعمال می‌شود — اختصاصی این جلسه، یا تنظیمات مشترک به‌عنوان پیش‌فرض"""
        if self.teacher_share_percent_override is not None:
            return self.teacher_share_percent_override
        setting = GroupPriceSetting.objects.order_by('-updated_at').first()
        return setting.teacher_share_percent if setting else 70

    @property
    def teacher_share(self):
        return int(self.total_price * self.teacher_share_percent_effective / 100)

    @property
    def school_share(self):
        return self.total_price - self.teacher_share

    def __str__(self):
        return f"{self.get_session_type_display()} - {self.language_level} ({self.get_status_display()})"


class GroupSessionParticipant(models.Model):
    """یک نفر که به یک GroupSession ملحق شده — قیمت هرنفر همیشه از خودِ جلسه (پلکان فعلی) خوانده می‌شود، نه ذخیره‌ی ثابت"""

    class PaymentStatus(models.TextChoices):
        UNPAID = 'unpaid', 'پرداخت نشده'
        PAID = 'paid', 'پرداخت شده'
        PENDING = 'pending', 'در انتظار تایید'

    group_session = models.ForeignKey(GroupSession, on_delete=models.CASCADE, related_name='participants')
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='group_session_participations', limit_choices_to={'role': 'student'})
    payment_status = models.CharField(max_length=10, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    receipt = models.ImageField(upload_to='group_receipts/', null=True, blank=True)
    satisfaction = models.IntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    satisfaction_text = models.TextField(blank=True)
    satisfaction_approved = models.BooleanField(default=False)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('group_session', 'student')
        ordering = ['joined_at']

    @property
    def price_amount(self):
        return self.group_session.get_price_per_person()

    def __str__(self):
        return f"{self.student} - {self.group_session}"


class GroupSessionMeeting(models.Model):
    """جلسه‌ی مجزا از یک GroupSession (وقتی session_count > 1) — تاریخ/ساعت اتمام هرکدام جدا و همیشه قابل ویرایش است"""
    group_session = models.ForeignKey(GroupSession, on_delete=models.CASCADE, related_name='meetings')
    meeting_number = models.PositiveIntegerField()
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['meeting_number']
        unique_together = ('group_session', 'meeting_number')

    @property
    def completed_at_jalali(self):
        if not self.completed_at:
            return None
        local_dt = timezone.localtime(self.completed_at)
        return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')

    def __str__(self):
        return f"جلسه {self.meeting_number} - {self.group_session}"


class GroupSessionAttendance(models.Model):
    """
    حضور/غیاب و وضعیت پرداخت هر شرکت‌کننده برای هر جلسه‌ی مجزا (meeting) به‌صورت مستقل.
    هم در پنل ادمین وب و هم در اپ استاد قابل ثبت/ویرایش است.
    """

    class Status(models.TextChoices):
        UNMARKED = 'unmarked', 'ثبت‌نشده'
        PRESENT = 'present', 'حاضر'
        ABSENT = 'absent', 'غایب'

    meeting = models.ForeignKey('GroupSessionMeeting', on_delete=models.CASCADE, related_name='attendances')
    participant = models.ForeignKey('GroupSessionParticipant', on_delete=models.CASCADE, related_name='attendances')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.UNMARKED)
    paid = models.BooleanField(default=False)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('meeting', 'participant')

    def __str__(self):
        return f"{self.participant.student} - جلسه {self.meeting.meeting_number} ({self.get_status_display()})"


def ensure_attendance_rows(meeting):
    """ردیف‌های حضور/غیاب موجود نشده برای همه‌ی شرکت‌کننده‌های فعلی جلسه رو می‌سازه (idempotent)"""
    existing = set(meeting.attendances.values_list('participant_id', flat=True))
    to_create = [
        GroupSessionAttendance(meeting=meeting, participant=p)
        for p in meeting.group_session.participants.all() if p.id not in existing
    ]
    if to_create:
        GroupSessionAttendance.objects.bulk_create(to_create)
    return meeting.attendances.select_related('participant__student').order_by('participant__joined_at')


def ensure_meetings(group_session):
    """ردیف‌های جلسه‌ی موجود نشده رو تا session_count می‌سازه (idempotent)"""
    existing = set(group_session.meetings.values_list('meeting_number', flat=True))
    to_create = [
        GroupSessionMeeting(group_session=group_session, meeting_number=n)
        for n in range(1, group_session.session_count + 1) if n not in existing
    ]
    if to_create:
        GroupSessionMeeting.objects.bulk_create(to_create)
    return group_session.meetings.order_by('meeting_number')
