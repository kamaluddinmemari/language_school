from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('notifications', '0012_dailytaskreply_chat_features'),
    ]

    operations = [
        migrations.AddField(
            model_name='dailytask',
            name='audience_mode',
            field=models.CharField(choices=[('normal', 'عادی'), ('confidential', 'محرمانه')], default='normal', max_length=20),
        ),
    ]
