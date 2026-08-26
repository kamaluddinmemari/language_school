from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('payroll', '0007_employeeprofile_minimum_monthly_hours_and_auto_adjustments'),
    ]

    operations = [
        migrations.AddField(
            model_name='salaryprofile',
            name='hourly_shortfall_threshold',
            field=models.DecimalField(decimal_places=2, default=2.5, help_text='سقف کسر ساعتی بابت کسری کارکرد', max_digits=5),
        ),
        migrations.AddField(
            model_name='salaryprofile',
            name='leave_day_threshold',
            field=models.DecimalField(decimal_places=2, default=5, help_text='تعداد ساعت کسری برای کسر یک روز مرخصی استحقاقی', max_digits=5),
        ),
        migrations.AddField(
            model_name='monthlypayroll',
            name='hourly_shortfall_threshold',
            field=models.DecimalField(decimal_places=2, default=2.5, help_text='سقف کسر ساعتی ثبت‌شده برای این فیش', max_digits=5),
        ),
        migrations.AddField(
            model_name='monthlypayroll',
            name='leave_day_threshold',
            field=models.DecimalField(decimal_places=2, default=5, help_text='آستانهٔ کسر یک روز مرخصی ثبت‌شده برای این فیش', max_digits=5),
        ),
    ]
