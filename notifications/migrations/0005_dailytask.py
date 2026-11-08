from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('notifications', '0004_alter_webpushsubscription_id'),
    ]

    operations = [
        migrations.CreateModel(
            name='DailyTask',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=180)),
                ('body', models.TextField()),
                ('link_label', models.CharField(blank=True, default='اینجا', max_length=80)),
                ('link_url', models.CharField(blank=True, default='', max_length=300)),
                ('start_date', models.DateField(default=django.utils.timezone.localdate)),
                ('end_date', models.DateField(blank=True, null=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assigned_to', models.ManyToManyField(blank=True, help_text='خالی = مشترک برای همه کارکنان', related_name='daily_tasks', to=settings.AUTH_USER_MODEL)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_daily_tasks', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['start_date', 'created_at', 'id']},
        ),
        migrations.CreateModel(
            name='DailyTaskCompletion',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('completed_on', models.DateField(default=django.utils.timezone.localdate)),
                ('completed_at', models.DateTimeField(auto_now_add=True)),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily_task_completions', to=settings.AUTH_USER_MODEL)),
                ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='completions', to='notifications.dailytask')),
            ],
            options={'ordering': ['-completed_at']},
        ),
        migrations.AddConstraint(
            model_name='dailytaskcompletion',
            constraint=models.UniqueConstraint(fields=('task', 'employee', 'completed_on'), name='unique_daily_task_employee_day_completion'),
        ),
    ]
