# Generated manually for the private-class workflow flowchart.
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0040_classrequest_priority_and_contact'),
    ]

    operations = [
        migrations.AddField(
            model_name='classrequest',
            name='workflow_stage',
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='teacher_proposed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='student_time_confirmed',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='student_time_rejected',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='stage1_notes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='stage2_notes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='stage3_notes',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='stage4_notes',
            field=models.TextField(blank=True),
        ),
    ]
