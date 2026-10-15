from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('leads', '0027_excel_dropout_nullable_from_term'),
        ('class_management', '0030_classslotenrollment_carryover_tracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='unregisteredstudent',
            name='reported_slot',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='class_management.classslot'),
        ),
    ]
