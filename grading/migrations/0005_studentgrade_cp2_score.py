from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('grading', '0004_gradefieldsetting_oral_choice'),
    ]

    operations = [
        migrations.AddField(
            model_name='studentgrade',
            name='cp2_score',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
