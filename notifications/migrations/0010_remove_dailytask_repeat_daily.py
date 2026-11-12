from django.db import migrations


class Migration(migrations.Migration):
    """ستون repeat_daily (که در 0008 اضافه شد) حذف می‌شود؛ تکرار روزانه حالا با تاریخ پایانِ نمادین ذخیره می‌شود."""
    dependencies = [('notifications', '0009_dailytaskreply')]
    operations = [migrations.RemoveField(model_name='dailytask', name='repeat_daily')]
