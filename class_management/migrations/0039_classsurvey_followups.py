from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0038_classsurvey'),
    ]

    operations = [
        migrations.AddField(
            model_name='classsurveylist',
            name='deadline_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='classsurveylist',
            name='deadline_days',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='classsurveylist',
            name='deadline_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='classsurveylist',
            name='deadline_mode',
            field=models.CharField(
                choices=[
                    ('none', 'بدون مهلت'),
                    ('date', 'تاریخ ثابت'),
                    ('automatic', 'خودکار از تاریخ ایجاد'),
                    ('session', 'بر اساس جلسهٔ کلاس'),
                ],
                default='none',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='classsurveylist',
            name='deadline_session_number',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='classsurveylist',
            name='use_teacher_class_sampling',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='classsurveylist',
            name='teacher_class_percentage',
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='classsurveyresponse',
            name='call_status',
            field=models.CharField(
                blank=True,
                choices=[('', 'ثبت نشده'), ('answered', 'پاسخ داده شد'), ('no_answer', 'پاسخ نداد')],
                default='',
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name='classsurveyresponse',
            name='contacted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='classsurveyresponse',
            name='due_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='classsurveyresponse',
            name='respondent_name',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddIndex(
            model_name='classsurveyresponse',
            index=models.Index(fields=['survey_list', 'completed', 'due_at'], name='class_manag_survey__9bcf4d_idx'),
        ),
    ]
