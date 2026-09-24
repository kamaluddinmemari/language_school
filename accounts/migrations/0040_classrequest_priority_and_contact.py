# Generated manually (no network access to run makemigrations in this environment).
# خواسته: دکمه‌ی تغییر اولویت (بردن به بالای صف)، دکمه‌ی انتقال به انتهای صف، و دکمه‌ی
# «با فرد تماس گرفته شد، پاسخگو نبود».

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0039_classrequest_payment_details'),
    ]

    operations = [
        migrations.AddField(
            model_name='classrequest',
            name='manual_priority',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='force_last',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='contact_no_answer',
            field=models.BooleanField(default=False),
        ),
    ]
