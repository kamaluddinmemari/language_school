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
EVENING_LATE_TIME_SLOTS = ['17:30-19:00', '19:00-20:30']  # برای زبان‌آموزان چرخشی — بعد از ۱۷:۳۰
THURSDAY_MORNING_SLOT = '08:00-13:00'
THURSDAY_EVENING_SLOT = '13:00-17:00'
FRIDAY_SLOT = '08:30-13:15'

ALL_STANDARD_TIME_SLOTS = MORNING_TIME_SLOTS + EVENING_TIME_SLOTS + [THURSDAY_MORNING_SLOT, THURSDAY_EVENING_SLOT, FRIDAY_SLOT]


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

    number = models.PositiveIntegerField(help_text='شماره کلاس — همان شماره می‌تواند در چند ساعت/روز مختلف تکرار شود (مثلاً کلاس ۱ هم صبح هم عصر)')
    title = models.CharField(max_length=100, blank=True)
    day_type = models.CharField(max_length=20, choices=DayType.choices)
    time_slot = models.CharField(max_length=20, blank=True, help_text='ساعت جاری کلاس — ترجیحاً از لیست استاندارد')
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
                fields=['number', 'day_type', 'time_slot'],
                name='unique_class_number_per_day_time',
                violation_error_message='این شماره کلاس دقیقاً در همین روز و همین ساعت از قبل وجود دارد',
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
