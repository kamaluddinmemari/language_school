# Generated manually: ذخیرهٔ وضعیت و نتیجهٔ پیگیریِ ثبت‌نام دانش‌آموز بین دو ترم.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0028_classslot_friday_morning_evening'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TermRetentionFollowUp',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[
                    ('needs_follow_up', 'نیازمند پیگیری'),
                    ('temporary_pause', 'وقفه موقت'),
                    ('dropout_confirmed', 'ریزش تأییدشده'),
                    ('graduated', 'پایان دوره / فارغ‌التحصیلی'),
                    ('transferred', 'انتقال به مؤسسهٔ دیگر'),
                    ('no_response', 'عدم پاسخ'),
                    ('other', 'سایر'),
                ], default='needs_follow_up', max_length=24)),
                ('reason', models.CharField(blank=True, choices=[
                    ('financial', 'هزینه / شهریه'),
                    ('schedule', 'زمان‌بندی کلاس'),
                    ('dissatisfaction', 'نارضایتی از دوره یا آموزش'),
                    ('relocation', 'جابجایی / دوری مسیر'),
                    ('family', 'شرایط خانوادگی یا شخصی'),
                    ('completed', 'پایان سطح یا دوره'),
                    ('other', 'سایر'),
                ], max_length=24)),
                ('notes', models.TextField(blank=True)),
                ('next_follow_up_date', models.DateField(blank=True, null=True)),
                ('last_contacted_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('current_term', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='retention_followups_as_current', to='class_management.term',
                )),
                ('previous_term', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='retention_followups_as_previous', to='class_management.term',
                )),
                ('student', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='term_retention_followups', to=settings.AUTH_USER_MODEL,
                )),
                ('updated_by', models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name='updated_term_retention_followups', to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['-updated_at']},
        ),
        migrations.AddConstraint(
            model_name='termretentionfollowup',
            constraint=models.UniqueConstraint(
                fields=('student', 'previous_term', 'current_term'),
                name='unique_student_term_retention_pair',
            ),
        ),
    ]
