# Generated manually (no network access to run makemigrations in this environment).
# فقط choices فیلد day_type به‌روزرسانی می‌شود — دو گزینه‌ی جدید «جمعه صبح» و «جمعه عصر»
# اضافه می‌شوند؛ گزینه‌ی قدیمی «friday» برای کلاس‌های از قبل ساخته‌شده دست‌نخورده می‌ماند.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0027_merge_20260917_1344'),
    ]

    operations = [
        migrations.AlterField(
            model_name='classslot',
            name='day_type',
            field=models.CharField(
                choices=[
                    ('even', 'روز زوج (سه روز در هفته)'),
                    ('two_day', 'دو روز در هفته'),
                    ('rotating', 'چرخشی صبح/عصر'),
                    ('odd', 'روز فرد (سه روز در هفته)'),
                    ('thursday_morning', 'یک روز در هفته - پنجشنبه صبح'),
                    ('thursday_evening', 'یک روز در هفته - پنجشنبه عصر'),
                    ('friday', 'یک روز در هفته - جمعه'),
                    ('friday_morning', 'یک روز در هفته - جمعه صبح'),
                    ('friday_evening', 'یک روز در هفته - جمعه عصر'),
                    ('online', 'آنلاین'),
                    ('hybrid', 'ترکیبی (آنلاین و حضوری)'),
                ],
                max_length=20,
            ),
        ),
    ]
