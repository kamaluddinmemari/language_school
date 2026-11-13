from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0037_newlead_no_response'),
    ]

    operations = [
        migrations.AddField(
            model_name='debtor',
            name='not_coming',
            field=models.BooleanField(default=False, help_text='علامت‌گذاری شده که فرد کلاً نمی‌آید'),
        ),
    ]
