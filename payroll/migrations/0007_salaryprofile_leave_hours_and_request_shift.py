from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('payroll', '0006_remove_salaryprofile_unique_salary_profile_per_user_year_and_more')]

    operations = [
        migrations.AddField(
            model_name='salaryprofile', name='morning_leave_hours',
            field=models.DecimalField(decimal_places=2, default=3, help_text='ساعت کارکرد مرخصی صبح', max_digits=4),
        ),
        migrations.AddField(
            model_name='salaryprofile', name='evening_leave_hours',
            field=models.DecimalField(decimal_places=2, default=5, help_text='ساعت کارکرد مرخصی عصر', max_digits=4),
        ),
        migrations.AddField(
            model_name='leaverequest', name='leave_shift',
            field=models.CharField(choices=[('morning', 'مرخصی صبح'), ('evening', 'مرخصی عصر')], default='morning', help_text='برای مرخصی روزانه', max_length=10),
        ),
    ]
