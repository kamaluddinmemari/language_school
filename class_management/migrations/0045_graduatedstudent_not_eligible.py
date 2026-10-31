from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0044_graduatedstudentclassselection'),
    ]

    operations = [
        migrations.AddField(
            model_name='graduatedstudentinfo',
            name='not_eligible',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='graduatedstudentinfo',
            name='not_eligible_archived',
            field=models.BooleanField(default=False),
        ),
    ]
