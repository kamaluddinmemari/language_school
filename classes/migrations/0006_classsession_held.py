from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('classes', '0005_classsession_cancel_fields')]

    operations = [
        migrations.AddField(
            model_name='classsession',
            name='held',
            field=models.BooleanField(default=False),
        ),
    ]
