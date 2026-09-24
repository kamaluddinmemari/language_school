# Generated manually (no network access to run makemigrations in this environment).
# خواسته: علامت‌گذاری درخواست‌های کلاسی که خودکار از نتیجه‌ی «تعیین سطح» ساخته شده‌اند، برای
# نمایش برچسب «ورود اطلاعات از تعیین سطح».

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0037_classrequest_coordination_flags'),
        ('level_tests', '0015_leveltest_reminders'),
    ]

    operations = [
        migrations.AddField(
            model_name='classrequest',
            name='source_level_test',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='auto_created_class_requests', to='level_tests.leveltest'),
        ),
    ]
