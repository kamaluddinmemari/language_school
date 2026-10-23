from django.conf import settings
from django.db import migrations, models

import accounts.archive


class Migration(migrations.Migration):
    dependencies = [
        ('grading', '0001_initial'),
        ('class_management', '0037_keep_current_term_records_on_student_delete'),
        ('accounts', '0047_archived_student_keep_records'),
    ]

    operations = [
        migrations.AlterField(
            model_name='studentgrade',
            name='student',
            field=models.ForeignKey(limit_choices_to={'role': 'student'}, on_delete=accounts.archive.keep_current_term_records, related_name='grades', to=settings.AUTH_USER_MODEL),
        ),
    ]
