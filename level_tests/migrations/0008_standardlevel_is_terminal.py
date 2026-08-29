from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('level_tests', '0007_leveltest_meeting_link_leveltest_mode_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='standardlevel',
            name='is_terminal',
            field=models.BooleanField(default=False, help_text='سطح پایانی این رده — بعد از این سطح دانش‌آموز برای ترم بعد نیازمند تعیین سطح مجدد است. فقط یک سطح پایانی در هر رده معتبر است.'),
        ),
    ]
