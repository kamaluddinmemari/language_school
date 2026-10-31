from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('leads', '0034_employeefollowupdeadlinerule_followup_type')]

    operations = [
        migrations.AlterField(
            model_name='employeefollowupdeadlinerule',
            name='followup_type',
            field=models.CharField(
                choices=[
                    ('unregistered', 'پیگیری افراد ثبت‌نام‌نشده'),
                    ('debtors', 'پیگیری بدهکاران'),
                    ('waiting-list', 'پیگیری لیست انتظار'),
                    ('consecutive-dropouts', 'پیگیری ریزشی‌های دو ترم متوالی'),
                    ('class-survey', 'پیگیری نظرسنجی کلاس‌ها'),
                    ('graduate-information', 'ارسال و دریافت اطلاعات فارغ‌التحصیلان'),
                ],
                default='unregistered', max_length=30,
            ),
        ),
    ]
