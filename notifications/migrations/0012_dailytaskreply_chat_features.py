from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('notifications', '0011_alter_contactfeedback_seen_by_admin'),
    ]

    operations = [
        migrations.AddField(
            model_name='dailytaskreply',
            name='attachment',
            field=models.FileField(blank=True, null=True, upload_to='daily-task-replies/%Y/%m/'),
        ),
        migrations.AddField(
            model_name='dailytaskreply',
            name='scheduled_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='dailytaskreply',
            name='updated_at',
            field=models.DateTimeField(auto_now=True),
        ),
    ]
