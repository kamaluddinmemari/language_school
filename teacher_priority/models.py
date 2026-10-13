from django.conf import settings
from django.db import models

from .scoring import ScoringConfig


class TeacherPriorityConfig(models.Model):
    """تنظیمات تک‌ردیفیِ سیستم امتیاز/اولویت استادها (همه‌چیز قابل تعریف از پنل)."""
    key = models.CharField(max_length=32, unique=True, default='default')

    # وزن معیارها — مجموع چهار وزن مثبت باید ۱۰۰ باشد
    w_parity = models.DecimalField(max_digits=6, decimal_places=2, default=25, help_text='وزن تنوع برنامه (زوج/فرد)')
    w_students = models.DecimalField(max_digits=6, decimal_places=2, default=25, help_text='وزن تعداد دانش‌آموزان ترم')
    w_one_day = models.DecimalField(max_digits=6, decimal_places=2, default=25, help_text='وزن کلاس‌های یک‌روز در هفته')
    w_class_count = models.DecimalField(max_digits=6, decimal_places=2, default=25, help_text='وزن تعداد کلاس‌های ترم')
    parity_even_only_ratio = models.DecimalField(max_digits=4, decimal_places=2, default='0.55', help_text='نسبت امتیاز «فقط زوج» به وزن تنوع')
    parity_odd_only_ratio = models.DecimalField(max_digits=4, decimal_places=2, default='0.35', help_text='نسبت امتیاز «فقط فرد» به وزن تنوع (باید کمتر از فقط‌زوج باشد)')
    student_target = models.PositiveIntegerField(default=60, help_text='تعداد دانش‌آموزی که امتیاز کامل معیار دانش‌آموز را می‌دهد')
    class_count_target = models.PositiveIntegerField(default=6, help_text='تعداد کلاسی که امتیاز کامل معیار تعداد کلاس را می‌دهد')
    absence_penalty_per_event = models.DecimalField(max_digits=5, decimal_places=2, default=4, help_text='امتیاز منفی هر غیبتِ تاییدشده در ترم')
    absence_penalty_cap = models.DecimalField(max_digits=5, decimal_places=2, default=20, help_text='سقف مجموع امتیاز منفی غیبت در یک ترم')

    # کسر امتیاز بابت هر جلسه‌ی کلاس خصوصی/جبرانی که به استاد داده می‌شود (جبرانی کمتر)
    private_session_penalty = models.DecimalField(max_digits=5, decimal_places=2, default=3, help_text='کسر امتیاز اولویت به‌ازای هر جلسه‌ی کلاس خصوصی')
    makeup_session_penalty = models.DecimalField(max_digits=5, decimal_places=2, default='1.5', help_text='کسر امتیاز اولویت به‌ازای هر جلسه‌ی کلاس جبرانی (کمتر از خصوصی)')

    # اثر روی دستمزد
    apply_to_hourly_price = models.BooleanField(default=False, help_text='اگر روشن باشد، امتیاز اولویت با ضریب زیر روی قیمت هر جلسه/ساعت استاد اثر می‌گذارد')
    price_coefficient = models.DecimalField(max_digits=5, decimal_places=2, default='0.20', help_text='ضریب اثر: قیمت × (۱ + ضریب × امتیاز/۱۰۰). مثلاً ۰٫۲۰ یعنی امتیاز ۱۰۰ = ۲۰٪ افزایش')

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        verbose_name = 'تنظیمات امتیاز اولویت استادها'

    FIELDS = (
        'w_parity', 'w_students', 'w_one_day', 'w_class_count',
        'parity_even_only_ratio', 'parity_odd_only_ratio', 'student_target', 'class_count_target',
        'absence_penalty_per_event', 'absence_penalty_cap',
        'private_session_penalty', 'makeup_session_penalty',
        'apply_to_hourly_price', 'price_coefficient',
    )

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(key='default')
        return obj

    def scoring_config(self) -> ScoringConfig:
        return ScoringConfig(
            w_parity=float(self.w_parity), w_students=float(self.w_students),
            w_one_day=float(self.w_one_day), w_class_count=float(self.w_class_count),
            parity_even_only_ratio=float(self.parity_even_only_ratio),
            parity_odd_only_ratio=float(self.parity_odd_only_ratio),
            student_target=int(self.student_target), class_count_target=int(self.class_count_target),
            absence_penalty_per_event=float(self.absence_penalty_per_event),
            absence_penalty_cap=float(self.absence_penalty_cap),
        )

    def payload(self):
        out = {}
        for f in self.FIELDS:
            v = getattr(self, f)
            out[f] = v if isinstance(v, (bool, int)) else float(v)
        return out

    def __str__(self):
        return 'تنظیمات امتیاز اولویت استادها'
