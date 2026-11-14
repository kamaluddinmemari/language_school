from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0039_unregistered_student_not_coming'),
    ]

    operations = [
        migrations.AddField(
            model_name='unregisteredstudent',
            name='attendance_transfer',
            field=models.CharField(
                blank=True, default='', max_length=14,
                choices=[('', 'خیر'), ('attending', 'در کلاس حضور دارد'), ('not_in_class', 'اصلاً در این کلاس نیست')],
                help_text='اگر از دکمه‌های حضور و غیابِ اپ به پیگیری منتقل شده باشد، نوع انتقال',
            ),
        ),
    ]
