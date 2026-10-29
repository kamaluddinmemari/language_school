from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0042_graduatedstudentinfo'),
    ]

    operations = [
        migrations.AddField(
            model_name='graduatedstudentinfo',
            name='excluded',
            field=models.BooleanField(default=False),
        ),
    ]
