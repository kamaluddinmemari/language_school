from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("level_tests", "0019_leveltest_queue_priority_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="leveltest",
            name="previous_missed_test_date",
            field=models.DateTimeField(
                blank=True,
                help_text="وقت قبلی که فرد مراجعه نکرد و سپس به صف تعیین سطح بازگشت",
                null=True,
            ),
        ),
    ]
