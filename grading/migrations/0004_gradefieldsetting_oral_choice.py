from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('grading', '0003_studentgrade_oral_score'),
    ]

    operations = [
        migrations.AlterField(
            model_name='gradefieldsetting',
            name='field_key',
            field=models.CharField(
                choices=[
                    ('cp', 'CP'),
                    ('midterm', 'میان‌ترم'),
                    ('writing1', 'رایتینگ ۱'),
                    ('writing2', 'رایتینگ ۲'),
                    ('oral', 'Oral'),
                    ('final', 'پایان‌ترم'),
                ],
                max_length=20,
            ),
        ),
    ]
