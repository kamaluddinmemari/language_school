from django.conf import settings
from django.db import migrations, models

import accounts.archive


class Migration(migrations.Migration):
    dependencies = [
        ('leads', '0029_row_descriptions'),
        ('accounts', '0047_archived_student_keep_records'),
    ]

    operations = [
        migrations.AlterField(
            model_name='dropoutfollowup',
            name='student',
            field=models.ForeignKey(on_delete=accounts.archive.keep_as_archived_student, related_name='dropout_followups', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='exceldropout',
            name='student',
            field=models.ForeignKey(on_delete=accounts.archive.keep_as_archived_student, related_name='excel_dropouts', to=settings.AUTH_USER_MODEL),
        ),
    ]
