from django.db import migrations, models


def mark_rows_with_followups_as_contacted(apps, schema_editor):
    UnregisteredStudent = apps.get_model('leads', 'UnregisteredStudent')
    Debtor = apps.get_model('leads', 'Debtor')
    UnregisteredStudent.objects.filter(followups__isnull=False).update(contacted=True)
    Debtor.objects.filter(followups__isnull=False).update(contacted=True)


class Migration(migrations.Migration):
    dependencies = [
        ('leads', '0041_never_came_alerts'),
    ]

    operations = [
        migrations.AddField(
            model_name='unregisteredstudent',
            name='contacted',
            field=models.BooleanField(default=False, help_text='برای این فرد تماس گرفته شده است'),
        ),
        migrations.AddField(
            model_name='debtor',
            name='contacted',
            field=models.BooleanField(default=False, help_text='برای این فرد تماس گرفته شده است'),
        ),
        migrations.RunPython(mark_rows_with_followups_as_contacted, migrations.RunPython.noop),
    ]
