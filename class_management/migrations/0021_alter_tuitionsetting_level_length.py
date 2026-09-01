from django.db import migrations, models
from level_tests.levels import get_all_level_choices


class Migration(migrations.Migration):
    # عمداً به 0019 وابسته است تا در پروژه‌هایی که فایل 0020 را ندارند
    # زنجیره migration از کار نیفتد.
    dependencies = [
        ('class_management', '0019_roomqrtoken_teachercompensationsetting_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tuitionsetting',
            name='level',
            field=models.CharField(choices=get_all_level_choices, max_length=30),
        ),
    ]
