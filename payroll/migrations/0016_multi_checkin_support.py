from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('payroll', '0015_attendancelog_check_in_method_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='employeeprofile',
            name='allows_multiple_daily_attendance',
            field=models.BooleanField(default=False, help_text='برای نقش\u200cهایی مثل خدمات که ممکن است چندبار در روز ورود/خروج بزنند (مثلاً صبح و عصر جدا) — در حالت عادی هرکس فقط یک\u200cبار ورود و یک\u200cبار خروج در روز می\u200cتواند ثبت کند.'),
        ),
        migrations.RemoveConstraint(
            model_name='attendancelog',
            name='unique_attendance_per_user_day',
        ),
        migrations.AddIndex(
            model_name='attendancelog',
            index=models.Index(fields=['user', 'date'], name='attendance_user_date_idx'),
        ),
    ]
