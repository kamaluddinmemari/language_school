from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('payroll', '0006_remove_salaryprofile_unique_salary_profile_per_user_year_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='employeeprofile',
            name='minimum_monthly_hours',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='حداقل ساعت کارکرد ماهانهٔ اختصاصی این کارمند؛ در صورت خالی‌بودن، ساعت استاندارد ماه استفاده می‌شود',
                max_digits=6,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='monthlypayroll',
            name='auto_adjustments_enabled',
            field=models.BooleanField(default=True, help_text='اعمال خودکار کسری، مرخصی و اضافه‌کاری بر اساس حداقل ساعت'),
        ),
        migrations.AddField(
            model_name='monthlypayroll',
            name='automatic_leave_days',
            field=models.PositiveIntegerField(default=0, editable=False, help_text='روزهای استحقاقی کسرشدهٔ خودکار بابت کسری کارکرد'),
        ),
        migrations.AddField(
            model_name='monthlypayroll',
            name='automatic_carryover_hours',
            field=models.DecimalField(default=0, decimal_places=2, editable=False, help_text='کسری ساعت منتقلشده به ماه بعد', max_digits=6),
        ),
        migrations.AddField(
            model_name='monthlypayroll',
            name='automatic_adjustment_note',
            field=models.TextField(blank=True, editable=False, help_text='توضیح خودکار تعدیل کارکرد'),
        ),
    ]
