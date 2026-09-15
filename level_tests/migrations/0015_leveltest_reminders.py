from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [('level_tests', '0014_leveltest_natoos_registered'), ('leads', '0013_remove_debtor_national_code_and_more')]
    operations = [
        migrations.AddField(model_name='leveltest', name='reminder_24h_followed_at', field=models.DateTimeField(blank=True, null=True, help_text='زمان ثبت پیگیری هشدار ۲۴ ساعت قبل')),
        migrations.AddField(model_name='leveltest', name='reminder_2h_followed_at', field=models.DateTimeField(blank=True, null=True, help_text='زمان ثبت پیگیری هشدار ۲ ساعت قبل')),
        migrations.AddField(model_name='leveltest', name='followup_lead', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='source_level_tests', to='leads.newlead', help_text='ورودی جدید ساخته‌شده برای پیگیری این تعیین سطح')),
    ]
