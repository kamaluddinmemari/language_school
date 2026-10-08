from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0017_claims_settled_and_unregistered_claims'),
    ]

    operations = [
        migrations.AlterField(
            model_name='debtor',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'در حال پیگیری'),
                    ('settled', 'تسویه شد'),
                    ('registered', 'ثبت‌نام‌شده'),
                ],
                default='pending',
                max_length=10,
            ),
        ),
    ]
