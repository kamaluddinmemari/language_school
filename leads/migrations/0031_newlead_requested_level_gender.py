from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('leads', '0030_dropout_keep_records_on_student_delete'),
    ]

    operations = [
        migrations.AddField(
            model_name='newlead',
            name='requested_level',
            field=models.CharField(blank=True, default='', max_length=50, help_text='سطح مورد تقاضا برای ثبت‌نام ترم آینده (کد یکی از سطوح استاندارد)'),
        ),
        migrations.AddField(
            model_name='newlead',
            name='gender',
            field=models.CharField(blank=True, default='', max_length=10, help_text='جنسیت (female/male) برای شمارش متقاضیان هر سطح'),
        ),
    ]
