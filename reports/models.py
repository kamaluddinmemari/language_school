from django.conf import settings
from django.db import models
from django.utils import timezone
import jdatetime


class ReportDefinition(models.Model):
    """
    یک گزارش دلخواه ذخیره‌شده توسط مدیر — منبع داده + فیلدهای انتخابی + شرط‌ها +
    گروه‌بندی/تجمیع، همه به‌صورت JSON. اجرای واقعی کوئری در reports/query_engine.py
    و بر اساس whitelist فیلدهای reports/registry_custom.py انجام می‌شود (امن).
    """
    name = models.CharField(max_length=150)
    source_key = models.CharField(max_length=50, help_text='کلید منبع داده — از reports/registry_custom.py')
    fields = models.JSONField(default=list, help_text='لیست کلید فیلدهای انتخابی برای نمایش تخت (بدون گروه‌بندی)')
    filters = models.JSONField(default=list, help_text="لیست شرط‌ها: [{'field','op','value'}, ...]")
    group_by = models.JSONField(default=list, blank=True, help_text='لیست کلید فیلدهای گروه‌بندی (اختیاری)')
    aggregations = models.JSONField(default=list, blank=True, help_text="[{'field','func'}, ...] — فقط وقتی group_by پر باشد معنی دارد")
    date_override = models.BooleanField(default=False, help_text='اگر True باشد، فیلتر تاریخ سراسری صفحه روی این گزارش اعمال نمی‌شود')

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def created_at_jalali(self):
        if not self.created_at:
            return None
        local_dt = timezone.localtime(self.created_at)
        return jdatetime.datetime.fromgregorian(datetime=local_dt).strftime('%Y/%m/%d - %H:%M')

    def __str__(self):
        return self.name
