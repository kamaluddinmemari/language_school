import datetime

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0039_classsurvey_followups'),
        ('leads', '0032_newlead_assigned_to'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='EmployeeFollowupDeadlineRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enabled', models.BooleanField(default=False)),
                ('mode', models.CharField(choices=[('date', 'تاریخ مشخص'), ('term_week', 'هفتهٔ ترم')], default='date', max_length=12)),
                ('deadline_date', models.DateField(blank=True, null=True)),
                ('deadline_time', models.TimeField(default=datetime.time(23, 59))),
                ('deadline_week', models.PositiveSmallIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('term', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='employee_followup_deadline_rules', to='class_management.term')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('term',), name='unique_employee_followup_deadline_per_term')],
            },
        ),
    ]
