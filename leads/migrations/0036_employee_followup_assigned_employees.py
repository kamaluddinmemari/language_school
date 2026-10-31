from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('leads', '0035_employee_followup_graduate_information_deadline'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='employeefollowupdeadlinerule',
            name='assigned_employees',
            field=models.ManyToManyField(
                blank=True,
                related_name='employee_followup_deadline_rules',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
