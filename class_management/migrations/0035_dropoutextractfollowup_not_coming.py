from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0034_dropoutextractlist_source_term'),
    ]

    operations = [
        migrations.AddField(
            model_name='dropoutextractfollowup',
            name='not_coming',
            field=models.BooleanField(default=False),
        ),
    ]
