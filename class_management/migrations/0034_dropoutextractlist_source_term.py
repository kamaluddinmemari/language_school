from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0033_dropoutextractlist'),
    ]

    operations = [
        migrations.AddField(
            model_name='dropoutextractlist',
            name='source_term',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='class_management.term'),
        ),
    ]
