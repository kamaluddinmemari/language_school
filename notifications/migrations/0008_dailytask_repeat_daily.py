from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('notifications', '0007_dailytaskcompletion_note')]
    operations = [migrations.AddField(model_name='dailytask', name='repeat_daily', field=models.BooleanField(default=False, help_text='هر روز از تاریخ شروع تکرار می‌شود (تاریخ پایان نادیده گرفته می‌شود) و انجام‌شدن هر روز از نو ثبت می‌شود'))]
