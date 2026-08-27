from django.db import migrations


def repair_missing_schedule_columns(apps, schema_editor):
    ClassSlot = apps.get_model('class_management', 'ClassSlot')
    connection = schema_editor.connection
    table = ClassSlot._meta.db_table
    cursor = connection.cursor()
    existing = {c.name for c in connection.introspection.get_table_description(cursor, table)}
    definitions = [
        ('delivery_pattern', "TEXT NOT NULL DEFAULT '[]'"),
        ('rotation_group', "varchar(64) NOT NULL DEFAULT ''"),
        ('schedule_days', "TEXT NOT NULL DEFAULT '[]'"),
        ('schedule_kind', "varchar(20) NOT NULL DEFAULT 'standard'"),
    ]
    for name, sqlite_type in definitions:
        if name not in existing:
            if connection.vendor == 'sqlite':
                schema_editor.execute(
                    'ALTER TABLE %s ADD COLUMN %s %s' % (connection.ops.quote_name(table), connection.ops.quote_name(name), sqlite_type)
                )
            else:
                raise RuntimeError(f'ستون {name} در دیتابیس وجود ندارد؛ migration اصلی را برای این پایگاه‌داده اجرا کنید.')


class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0013_classslot_schedule_metadata'),
    ]

    operations = [
        migrations.RunPython(repair_missing_schedule_columns, migrations.RunPython.noop),
    ]
