from django.db import migrations, models


SCHEDULE_FIELD_DEFINITIONS = [
    ('delivery_pattern', models.JSONField(blank=True, default=list, help_text='ترکیب جلسه‌ها؛ مثلاً دو جلسه آنلاین و یک جلسه حضوری'), "TEXT NOT NULL DEFAULT '[]'"),
    ('rotation_group', models.CharField(blank=True, help_text='کلید مشترک کلاس چرخشی صبح/عصر؛ دانش‌آموز و استاد یکسان می‌ماند', max_length=64), "varchar(64) NOT NULL DEFAULT ''"),
    ('schedule_days', models.JSONField(blank=True, default=list, help_text='روزهای انتخاب‌شده برای کلاس‌های دو روزه یا چرخشی'), "TEXT NOT NULL DEFAULT '[]'"),
    ('schedule_kind', models.CharField(choices=[('standard', 'کلاس عادی'), ('two_day', 'دو روز در هفته'), ('hybrid', 'ترکیبی حضوری/مجازی'), ('rotating', 'چرخشی صبح/عصر')], default='standard', max_length=20), "varchar(20) NOT NULL DEFAULT 'standard'"),
]


def add_missing_schedule_columns(apps, schema_editor):
    ClassSlot = apps.get_model('class_management', 'ClassSlot')
    connection = schema_editor.connection
    table = ClassSlot._meta.db_table
    cursor = connection.cursor()
    existing = {c.name for c in connection.introspection.get_table_description(cursor, table)}
    for name, field, sqlite_type in SCHEDULE_FIELD_DEFINITIONS:
        if name in existing:
            continue
        if connection.vendor == 'sqlite':
            schema_editor.execute(
                'ALTER TABLE %s ADD COLUMN %s %s' % (connection.ops.quote_name(table), connection.ops.quote_name(name), sqlite_type)
            )
        else:
            field.model = ClassSlot
            schema_editor.add_field(ClassSlot, field)


class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0012_onlinecourseactionrequest'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_missing_schedule_columns, migrations.RunPython.noop)],
            state_operations=[
                migrations.AddField(model_name='classslot', name='delivery_pattern', field=SCHEDULE_FIELD_DEFINITIONS[0][1]),
                migrations.AddField(model_name='classslot', name='rotation_group', field=SCHEDULE_FIELD_DEFINITIONS[1][1]),
                migrations.AddField(model_name='classslot', name='schedule_days', field=SCHEDULE_FIELD_DEFINITIONS[2][1]),
                migrations.AddField(model_name='classslot', name='schedule_kind', field=SCHEDULE_FIELD_DEFINITIONS[3][1]),
            ],
        ),
        migrations.AlterField(
            model_name='classslot', name='day_type',
            field=models.CharField(
                choices=[('even', 'روز زوج (سه روز در هفته)'), ('two_day', 'دو روز در هفته'), ('rotating', 'چرخشی صبح/عصر'), ('odd', 'روز فرد (سه روز در هفته)'), ('thursday_morning', 'یک روز در هفته - پنجشنبه صبح'), ('thursday_evening', 'یک روز در هفته - پنجشنبه عصر'), ('friday', 'یک روز در هفته - جمعه'), ('online', 'آنلاین'), ('hybrid', 'ترکیبی (آنلاین و حضوری)')],
                max_length=20,
            ),
        ),
    ]
