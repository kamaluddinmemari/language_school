from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0038_debtor_not_coming'),
    ]

    operations = [
        migrations.AddField(
            model_name='unregisteredstudent',
            name='not_coming',
            field=models.BooleanField(default=False, help_text='علامت‌گذاری شده که فرد کلاً نمی‌آید'),
        ),
    ]
