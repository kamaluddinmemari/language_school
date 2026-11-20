from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('notifications', '0015_dailytask_archived_at')]
    operations = [
        migrations.AddField(
            model_name='dailytask',
            name='show_body_with_title',
            field=models.BooleanField(default=False, help_text='متن پیام در کنار عنوان دستور اطلاع‌رسانی نمایش داده شود'),
        ),
    ]
