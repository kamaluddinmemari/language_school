from django.db import migrations, models
from level_tests.levels import get_all_level_choices


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0017_rename_class_manag_term_id_8d01e3_idx_class_manag_term_id_ff5582_idx_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tuitionsetting',
            name='level',
            field=models.CharField(choices=get_all_level_choices, max_length=20),
        ),
        migrations.AlterField(
            model_name='levelrenewalapproval',
            name='level',
            field=models.CharField(max_length=20),
        ),
    ]
