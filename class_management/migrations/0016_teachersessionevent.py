from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0015_merge_20260827_1625'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TeacherSessionEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(choices=[('substitution', 'ساب استاد'), ('absence', 'غیبت و کنسلی'), ('makeup', 'جلسه جبرانی')], max_length=20)),
                ('class_date', models.DateField(help_text='تاریخ واقعی جلسه؛ به میلادی ذخیره و در پنل شمسی نمایش داده می‌شود')),
                ('session_number', models.PositiveSmallIntegerField(default=1, help_text='شماره جلسه از ۱ تا ۱۵')),
                ('requested_teacher_name', models.CharField(blank=True, max_length=150)),
                ('replacement_teacher_name', models.CharField(blank=True, max_length=150)),
                ('status', models.CharField(choices=[('pending', 'در انتظار تایید'), ('approved', 'تایید شده'), ('rejected', 'رد شده')], default='pending', max_length=15)),
                ('requested_at', models.DateTimeField(auto_now_add=True)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('makeup_required', models.BooleanField(default=False)),
                ('makeup_session_count', models.PositiveSmallIntegerField(default=0)),
                ('notes', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('approved_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='approved_teacher_session_events', to=settings.AUTH_USER_MODEL)),
                ('class_slot', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='teacher_session_events', to='class_management.classslot')),
                ('requested_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='requested_teacher_session_events', to=settings.AUTH_USER_MODEL)),
                ('term', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='teacher_session_events', to='class_management.term')),
            ],
            options={
                'ordering': ['-class_date', '-requested_at'],
                'indexes': [
                    models.Index(fields=['term', 'event_type', 'class_date'], name='class_manag_term_id_8d01e3_idx'),
                    models.Index(fields=['term', 'requested_teacher_name'], name='class_manag_term_id_2a5af7_idx'),
                    models.Index(fields=['term', 'replacement_teacher_name'], name='class_manag_term_id_5bf702_idx'),
                ],
            },
        ),
    ]
