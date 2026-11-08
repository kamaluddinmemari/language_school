from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('notifications', '0005_dailytask')]
    operations = [
        migrations.AddField(
            model_name='dailytask', name='start_time',
            field=models.TimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='dailytask', name='end_time',
            field=models.TimeField(blank=True, null=True),
        ),
    ]
