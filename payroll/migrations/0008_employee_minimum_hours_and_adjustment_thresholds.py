from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('payroll', '0007_salaryprofile_leave_hours_and_request_shift'),
    ]

    operations = [
        migrations.AddField(
            model_name='employeeprofile',
            name='minimum_monthly_hours',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='حداقل ساعات کارکرد ماهانه این کارمند؛ صفر یعنی ساعت استاندارد ماه',
                max_digits=6,
            ),
        ),
        migrations.AddField(
            model_name='salaryprofile',
            name='shortfall_hourly_threshold',
            field=models.DecimalField(
                decimal_places=2,
                default=2.5,
                help_text='حداکثر کسری‌ساعت برای کسر ساعتی',
                max_digits=4,
            ),
        ),
        migrations.AddField(
            model_name='salaryprofile',
            name='shortfall_leave_day_threshold',
            field=models.DecimalField(
                decimal_places=2,
                default=5,
                help_text='از این مقدار کسری به بعد یک روز مرخصی کسر می‌شود',
                max_digits=4,
            ),
        ),
    ]
