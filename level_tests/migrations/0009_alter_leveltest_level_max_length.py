from django.db import migrations, models
from level_tests.levels import get_all_level_choices


class Migration(migrations.Migration):

    dependencies = [
        ('level_tests', '0008_standardlevel_is_terminal'),
    ]

    operations = [
        migrations.AlterField(
            model_name='leveltest',
            name='level',
            field=models.CharField(blank=True, choices=get_all_level_choices, max_length=20),
        ),
    ]
