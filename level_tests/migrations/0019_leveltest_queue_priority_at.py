from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("level_tests", "0018_leveltest_sequence_warning"),
    ]

    operations = [
        migrations.AddField(
            model_name="leveltest",
            name="queue_priority_at",
            field=models.DateTimeField(
                blank=True,
                help_text="زمان انتقال دستی این فرد به ابتدای صف تعیین سطح",
                null=True,
            ),
        ),
    ]
