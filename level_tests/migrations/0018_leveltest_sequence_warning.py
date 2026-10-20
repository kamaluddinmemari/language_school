from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("level_tests", "0017_leveltest_manual_slot_override"),
    ]

    operations = [
        migrations.AddField(
            model_name="leveltest",
            name="sequence_warning",
            field=models.BooleanField(default=False, help_text="تعیین سطح برای این فرد به‌دلیل عدم توالی ترم الزامی است"),
        ),
    ]
