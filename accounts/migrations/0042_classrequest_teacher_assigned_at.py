from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0041_classrequest_workflow'),
    ]

    operations = [
        migrations.AddField(
            model_name='classrequest',
            name='teacher_assigned_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
