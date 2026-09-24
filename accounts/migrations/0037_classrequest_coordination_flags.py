# Generated manually (no network access to run makemigrations in this environment).
# خواسته: دو پرچمِ یک‌بارمصرفِ «هماهنگی با استاد» و «هماهنگی با دانش‌آموز» برای کلاس‌های
# تایید نهایی‌شده.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0036_merge_0035_dailyactivity_0035_merge_20260920_1005'),
    ]

    operations = [
        migrations.AddField(
            model_name='classrequest',
            name='teacher_coordinated',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='student_coordinated',
            field=models.BooleanField(default=False),
        ),
    ]
