from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('notifications', '0014_dailytask_is_information')]
    operations = [
        migrations.AddField(
            model_name='dailytask',
            name='archived_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
