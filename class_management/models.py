from django.db import models
from django.utils import timezone
import jdatetime


def _jalali(dt):
    if not dt:
        return None
    local_dt = timezone.localtime(dt)
    return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')


MORNING_TIME_SLOTS = ['08:00-09:30', '09:45-11:15', '11:30-13:00']
EVENING_TIME_SLOTS = ['15:45-17:15', '17:30-19:00', '19:00-20:30']
EVENING_LATE_TIME_SLOTS = ['17:30-19:00', '19:00-20:30']  # برای کلاس‌های چرخشی — بعد از ۱۷:۳۰
THURSDAY_MORNING_SLOT = '08:00-13:00'
THURSDAY_EVENING_SLOT = '13:00-17:00'
FRIDAY_SLOT = '08:30-13:15'


class ClassSlot(models.Model):
    """
    یک کلاس، که مدیر یکی‌یکی وارد می‌کند (نه لیست ثابت از پیش‌ساخته) — با روز هفتگی، وضعیت
    اکثریت زبان‌آموزانش (چرخشی/فقط‌صبح/...)، و ظرفیت. ساعت دقیق کلاس (برای کلاس‌های سه‌روزه)
    با دکمه‌ی «چیدمان هوشمند ساعت‌ها» بر اساس همین وضعیت خودکار محاسبه می‌شود، ولی همیشه هم
    مستقیم توسط مدیر قابل ویرایش است. حذف هر کلاس هم در هر لحظه آزاد است.
    """

    class DayType(models.TextChoices):
        EVEN = 'even', 'روز زوج (سه روز در هفته)'
        ODD = 'odd', 'روز فرد (سه روز در هفته)'
        THURSDAY_MORNING = 'thursday_morning', 'یک روز در هفته - پنجشنبه صبح'
        THURSDAY_EVENING = 'thursday_evening', 'یک روز در هفته - پنجشنبه عصر'
        FRIDAY = 'friday', 'یک روز در هفته - جمعه'

    class StudentStatus(models.TextChoices):
        ROTATING = 'rotating', 'چرخشی'
        ONLY_MORNING = 'only_morning', 'فقط صبح'
        ONE_DAY_PREFERENCE = 'one_day_preference', 'تمایل به کلاس یک روز در هفته'
        HYBRID_ONLINE = 'hybrid_online', 'ترکیب حضوری/مجازی و آنلاین'
        OTHER = 'other', 'سایر'

    number = models.PositiveIntegerField(unique=True, help_text='شماره کلاس')
    title = models.CharField(max_length=100, blank=True)
    day_type = models.CharField(max_length=20, choices=DayType.choices)

    # وضعیت اکثریت زبان‌آموزان این کلاس — پایه‌ی تصمیم‌گیری خودکار صبح/عصر
    is_rotating_majority = models.BooleanField(default=False, help_text='آیا اکثریت این کلاس وضعیت مدرسه‌ی چرخشی دارند؟')
    student_status = models.CharField(max_length=20, choices=StudentStatus.choices, blank=True)
    student_status_other = models.CharField(max_length=150, blank=True, help_text='توضیح دستی وقتی «سایر» انتخاب شده')

    capacity = models.PositiveIntegerField(default=10)
    teacher_name = models.CharField(max_length=150, blank=True)
    time_slot = models.CharField(max_length=20, blank=True, help_text='خودکار محاسبه می‌شود، ولی قابل ویرایش دستی هم هست')

    assigned_level = models.CharField(max_length=50, blank=True)
    current_count = models.PositiveIntegerField(default=0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['number']

    @property
    def day_type_display(self):
        return self.get_day_type_display()

    @property
    def student_status_display(self):
        if self.student_status == self.StudentStatus.OTHER and self.student_status_other:
            return self.student_status_other
        return self.get_student_status_display() if self.student_status else ''

    @property
    def is_three_day(self):
        return self.day_type in (self.DayType.EVEN, self.DayType.ODD)

    @property
    def is_effectively_rotating(self):
        return self.is_rotating_majority or self.student_status == self.StudentStatus.ROTATING

    @property
    def capacity_status(self):
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
    def updated_at_jalali(self):
        return _jalali(self.updated_at)

    def fixed_time_slot(self):
        """ساعت ثابت برای فرمت‌های تک‌روزه (زوج/فرد نیستند) — برای این‌ها نیازی به چیدمان هوشمند نیست"""
        return {
            self.DayType.THURSDAY_MORNING: THURSDAY_MORNING_SLOT,
            self.DayType.THURSDAY_EVENING: THURSDAY_EVENING_SLOT,
            self.DayType.FRIDAY: FRIDAY_SLOT,
        }.get(self.day_type)

    def save(self, *args, **kwargs):
        fixed = self.fixed_time_slot()
        if fixed:
            self.time_slot = fixed
        super().save(*args, **kwargs)

    def __str__(self):
        return f"کلاس {self.number} — {self.get_day_type_display()} ({self.time_slot or 'ساعت نامشخص'})"
