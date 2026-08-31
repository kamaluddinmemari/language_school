from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0025_user_last_generated_password'),
    ]

    operations = [
        migrations.AddField(
            model_name='menupermission',
            name='can_edit',
            field=models.BooleanField(default=False),
        ),
    ]
