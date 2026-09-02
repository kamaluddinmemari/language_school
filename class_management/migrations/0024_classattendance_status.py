from django.db import migrations, models


def migrate_legacy_attendance(apps, schema_editor):
    ClassAttendance = apps.get_model('class_management', 'ClassAttendance')
    ClassAttendance.objects.filter(is_present=True).update(status='present')
    ClassAttendance.objects.filter(is_present=False).update(status='absent')


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0023_remove_classattendance_session_number_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='classattendance',
            name='status',
            field=models.CharField(
                choices=[
                    ('present', 'حاضر'),
                    ('absent', 'غایب'),
                    ('late', 'تاخیر'),
                ],
                default='present',
                max_length=10,
            ),
        ),
        migrations.RunPython(migrate_legacy_attendance, migrations.RunPython.noop),
    ]
