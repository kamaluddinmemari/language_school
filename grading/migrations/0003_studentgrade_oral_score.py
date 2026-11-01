from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('grading', '0002_keep_current_term_grades_on_student_delete'),
    ]

    operations = [
        migrations.AddField(
            model_name='studentgrade',
            name='oral_score',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
