from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0045_formarchive'),
    ]

    operations = [
        migrations.AddField(
            model_name='classrequest',
            name='sequence_warning',
            field=models.BooleanField(default=False, db_index=True),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='sequence_warning_details',
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
