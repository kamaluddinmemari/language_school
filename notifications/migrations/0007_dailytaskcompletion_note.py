from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('notifications', '0006_dailytask_times')]
    operations = [migrations.AddField(model_name='dailytaskcompletion', name='note', field=models.TextField(blank=True, default=''))]
