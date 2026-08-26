from django.db import migrations, models


def backfill_level_identity(apps, schema_editor):
    Student = apps.get_model('leads', 'UnregisteredStudent')
    for row in Student.objects.all().iterator():
        old = row.identity_key or ''
        level = ' '.join(str(row.class_level or '').split()).casefold()
        row.identity_key = f"{old}|level:{level}" if level and '|level:' not in old else old
        row.save(update_fields=['identity_key'])


class Migration(migrations.Migration):
    dependencies = [('leads', '0007_term_identity_uniqueness')]
    operations = [migrations.RunPython(backfill_level_identity, migrations.RunPython.noop)]
