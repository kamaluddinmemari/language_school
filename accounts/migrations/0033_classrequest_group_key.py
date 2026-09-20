# Generated manually (no network access to run makemigrations in this environment).
# فیلد group_key برای گروه‌بندی نمایشی کلاس‌های خصوصی چند نفره اضافه می‌شود.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0032_alter_appaccesssettings_id_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='classrequest',
            name='group_key',
            field=models.CharField(blank=True, db_index=True, default='', help_text='برای کلاس خصوصی چند نفره — همه‌ی اعضای یک کلاس مشترک، این مقدار را یکسان دارند', max_length=40),
        ),
    ]
