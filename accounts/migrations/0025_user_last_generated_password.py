from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0024_employee_role_and_menupermission'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='last_generated_password',
            field=models.CharField(
                blank=True, max_length=32,
                help_text='آخرین رمز عبوری که مدیر برای این کاربر تنظیم کرده (متن خام، فقط برای نمایش به مدیر در '
                           '«تنظیمات دسترسی»؛ تا وقتی خودِ کاربر رمزش را عوض نکرده معتبر است — با هر بازیابی خودکار '
                           'رمز توسط کاربر خالی می‌شود).',
            ),
        ),
    ]
