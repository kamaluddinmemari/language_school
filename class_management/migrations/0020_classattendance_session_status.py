from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0019_roomqrtoken_teachercompensationsetting_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='classattendance',
            name='session_number',
            field=models.PositiveSmallIntegerField(default=1, help_text='شماره جلسه از ۱ تا ۱۵'),
        ),
        migrations.AddField(
            model_name='classattendance',
            name='status',
            field=models.CharField(choices=[('present', 'حاضر'), ('absent', 'غایب'), ('late', 'تاخیر'), ('early_leave', 'تعجیل'), ('excused', 'غیبت موجه')], default='present', max_length=20),
        ),
    ]
