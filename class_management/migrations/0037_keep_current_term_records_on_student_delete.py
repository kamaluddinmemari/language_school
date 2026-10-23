from django.conf import settings
from django.db import migrations, models

import accounts.archive


class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0036_classslot_carryover_source'),
        ('accounts', '0047_archived_student_keep_records'),
    ]

    operations = [
        migrations.AlterField(
            model_name='classslotenrollment',
            name='student',
            field=models.ForeignKey(on_delete=accounts.archive.keep_current_term_records, related_name='class_slot_enrollments', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='classattendance',
            name='student',
            field=models.ForeignKey(on_delete=accounts.archive.keep_current_term_records, related_name='class_attendances', to=settings.AUTH_USER_MODEL),
        ),
    ]
