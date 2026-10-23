from django.conf import settings
from django.db import migrations, models

import accounts.archive


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0046_classrequest_sequence_warning'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='archived_national_code',
            field=models.CharField(blank=True, default='', max_length=10, help_text='فقط برای پروندهٔ بایگانی‌شده: کد ملی دانش‌آموز حذف‌شده (یکتا نیست تا ثبت مجدد همان فرد مشکل نسازد)'),
        ),
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('admin', 'مدیر'), ('teacher', 'معلم'), ('student', 'دانش‌آموز'), ('evaluator', 'کارشناس آموزش'),
                    ('office', 'کارشناس اداری'), ('employee', 'کارمند'),
                    ('archived', 'پروندهٔ بایگانی‌شده (دانش‌آموز حذف‌شده)'),
                ],
                default='student', max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name='classrequest',
            name='student',
            field=models.ForeignKey(
                limit_choices_to={'role': 'student'}, on_delete=accounts.archive.keep_as_archived_student,
                related_name='requests', to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
