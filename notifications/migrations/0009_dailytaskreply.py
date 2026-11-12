from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('notifications', '0008_dailytask_repeat_daily'),
    ]
    operations = [
        migrations.CreateModel(
            name='DailyTaskReply',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('body', models.TextField()),
                ('created_on', models.DateField(default=django.utils.timezone.localdate)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='daily_task_replies', to=settings.AUTH_USER_MODEL)),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='children', to='notifications.dailytaskreply')),
                ('task', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='replies', to='notifications.dailytask')),
            ],
            options={'ordering': ['created_at', 'id']},
        ),
    ]
