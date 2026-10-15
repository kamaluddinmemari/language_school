from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0043_classrequest_refund_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='classrequest',
            name='is_urgent',
            field=models.BooleanField(db_index=True, default=False),
        ),
    ]
