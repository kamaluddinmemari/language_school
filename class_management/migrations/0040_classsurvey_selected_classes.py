from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0039_classsurvey_followups'),
    ]

    operations = [
        migrations.AddField(
            model_name='classsurveylist',
            name='selected_class_slot_ids',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
