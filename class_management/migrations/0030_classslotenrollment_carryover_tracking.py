# Generated manually: تفکیک فهرست حضور‌وغیاب منتقل‌شده از تمدید قطعی ثبت‌نام.
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0029_termretentionfollowup'),
    ]

    operations = [
        migrations.AddField(
            model_name='classslotenrollment',
            name='is_carryover',
            field=models.BooleanField(
                default=False,
                help_text='ثبت‌نام این ردیف برای حضور‌وغیاب از ترم قبل منتقل شده است',
            ),
        ),
        migrations.AddField(
            model_name='classslotenrollment',
            name='carryover_confirmed',
            field=models.BooleanField(
                default=False,
                help_text='تمدید ثبت‌نامِ دانش‌آموز منتقل‌شده برای این ترم قطعی شده است',
            ),
        ),
        migrations.AddField(
            model_name='classslotenrollment',
            name='carried_from_term',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='carried_class_enrollments',
                to='class_management.term',
            ),
        ),
    ]
