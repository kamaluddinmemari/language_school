# Generated manually (no network access to run makemigrations in this environment).
# مدل DailyActivity برای ثبت مدت زمان حضور روزانه‌ی هر کاربر در سایت.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('accounts', '0034_price_setting_group_pricing_and_group_size'),
    ]

    operations = [
        migrations.CreateModel(
            name='DailyActivity',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('total_seconds', models.PositiveIntegerField(default=0)),
                ('last_ping_at', models.DateTimeField()),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily_activities', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name='dailyactivity',
            constraint=models.UniqueConstraint(fields=('user', 'date'), name='unique_user_daily_activity'),
        ),
    ]
