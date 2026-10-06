from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0015_newleadfollowup'),
    ]

    operations = [
        migrations.AddField(
            model_name='debtor',
            name='claims_registered',
            field=models.BooleanField(default=False, help_text='فرد ادعا می‌کند ثبت‌نام کرده است ولی اسمش در لیست نیست — نیازمند بررسی'),
        ),
        migrations.AddField(
            model_name='debtor',
            name='claim_reviewed',
            field=models.BooleanField(default=False, help_text='ادعای ثبت‌نام بررسی شده است'),
        ),
    ]
