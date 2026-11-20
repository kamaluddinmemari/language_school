from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('notifications', '0013_dailytask_audience_mode')]
    operations = [
        migrations.AddField(
            model_name='dailytask',
            name='is_information',
            field=models.BooleanField(default=False, help_text='دستور اطلاع‌رسانی است و تیک انجام ندارد'),
        ),
    ]
