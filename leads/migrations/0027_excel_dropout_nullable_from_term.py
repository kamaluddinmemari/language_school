from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('leads', '0026_unregisteredstudent_gender'),
    ]

    operations = [
        migrations.AlterField(
            model_name='exceldropout',
            name='from_term',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='+', to='class_management.term'),
        ),
    ]
