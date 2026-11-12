from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0050_userhotkeysetting'),
    ]

    operations = [
        migrations.AddField(
            model_name='userhotkeysetting',
            name='sound_enabled',
            field=models.BooleanField(default=True),
        ),
    ]
