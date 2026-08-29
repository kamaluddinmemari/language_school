from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('payroll', '0008_employee_minimum_hours_and_adjustment_thresholds'),
    ]

    operations = [
        migrations.AddField(
            model_name='leaverequest', name='morning_days',
            field=models.PositiveIntegerField(default=0, help_text='در مرخصی ترکیبی، تعداد روزهای صبح'),
        ),
        migrations.AddField(
            model_name='leaverequest', name='evening_days',
            field=models.PositiveIntegerField(default=0, help_text='در مرخصی ترکیبی، تعداد روزهای عصر'),
        ),
        migrations.AlterField(
            model_name='leaverequest', name='leave_shift',
            field=models.CharField(choices=[('morning', 'مرخصی صبح'), ('evening', 'مرخصی عصر'), ('mixed', 'ترکیبی صبح و عصر')], default='morning', help_text='برای مرخصی روزانه', max_length=10),
        ),
        migrations.CreateModel(
            name='OfficialHoliday',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(unique=True)),
                ('title', models.CharField(default='تعطیلی رسمی', max_length=150)),
                ('is_active', models.BooleanField(default=True)),
                ('work_multiplier', models.DecimalField(decimal_places=2, default=1.75, help_text='ضریب کارکرد در تعطیلی رسمی', max_digits=4)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['-date']},
        ),
        migrations.CreateModel(
            name='HolidayWorkAssignment',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('include_in_worked_hours', models.BooleanField(default=False, help_text='در صورت فعال بودن، ساعات شیفت به کارکرد اضافه می‌شود')),
                ('shift', models.CharField(choices=[('morning', 'صبح'), ('evening', 'عصر'), ('mixed', 'ترکیبی صبح و عصر')], default='morning', max_length=10)),
                ('morning_days', models.PositiveIntegerField(default=0, help_text='برای بازه چندروزه، تعداد روزهای صبح')),
                ('evening_days', models.PositiveIntegerField(default=0, help_text='برای بازه چندروزه، تعداد روزهای عصر')),
                ('multiplier', models.DecimalField(blank=True, decimal_places=2, help_text='ضریب اختصاصی؛ خالی یعنی ضریب خود تعطیلی', max_digits=4, null=True)),
                ('notes', models.CharField(blank=True, max_length=255)),
                ('holiday', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='work_assignments', to='payroll.officialholiday')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='holiday_work_assignments', to=settings.AUTH_USER_MODEL)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('holiday', 'user'), name='unique_holiday_work_user')]},
        ),
    ]
