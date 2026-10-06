from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0016_debtor_claims_registered'),
    ]

    operations = [
        # در بدهکاران، تیک به «فرد می‌گوید بدهی تسویه شده» تغییر کرد
        migrations.RenameField(model_name='debtor', old_name='claims_registered', new_name='claims_settled'),
        migrations.AlterField(
            model_name='debtor',
            name='claims_settled',
            field=models.BooleanField(default=False, help_text='فرد می‌گوید بدهی‌اش تسویه شده است — نیازمند بررسی'),
        ),
        migrations.AlterField(
            model_name='debtor',
            name='claim_reviewed',
            field=models.BooleanField(default=False, help_text='ادعای تسویه بدهی بررسی شده است'),
        ),
        # تیک «فرد می‌گوید ثبت‌نام کرده ولی اسمش در لیست نیست» به افراد ثبت‌نام‌نشده منتقل شد
        migrations.AddField(
            model_name='unregisteredstudent',
            name='claims_registered',
            field=models.BooleanField(default=False, help_text='فرد می‌گوید ثبت‌نام کرده است ولی اسمش در لیست نیست — نیازمند بررسی'),
        ),
        migrations.AddField(
            model_name='unregisteredstudent',
            name='claim_reviewed',
            field=models.BooleanField(default=False, help_text='ادعای ثبت‌نام بررسی شده است'),
        ),
    ]
