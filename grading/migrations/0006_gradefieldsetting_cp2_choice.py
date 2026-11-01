from django.db import migrations, models


def rename_default_cp_title(apps, schema_editor):
    GradeFieldSetting = apps.get_model('grading', 'GradeFieldSetting')
    GradeFieldSetting.objects.filter(field_key='cp', title='CP').update(title='CP1')


class Migration(migrations.Migration):
    dependencies = [
        ('grading', '0005_studentgrade_cp2_score'),
    ]

    operations = [
        migrations.AlterField(
            model_name='gradefieldsetting',
            name='field_key',
            field=models.CharField(
                choices=[
                    ('cp', 'CP1'),
                    ('cp2', 'CP2'),
                    ('midterm', 'میان‌ترم'),
                    ('writing1', 'رایتینگ ۱'),
                    ('writing2', 'رایتینگ ۲'),
                    ('oral', 'Oral'),
                    ('final', 'پایان‌ترم'),
                ],
                max_length=20,
            ),
        ),
        migrations.RunPython(rename_default_cp_title, migrations.RunPython.noop),
    ]
