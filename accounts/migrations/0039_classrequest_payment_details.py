# Generated manually (no network access to run makemigrations in this environment).
# خواسته: نوع پرداخت (نقدی/کارت به کارت/پوز)، شماره‌ی پرداخت، و تاریخ/ساعت پرداخت برای
# هزینه‌ی کلاس خصوصی/جبرانی.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0038_classrequest_source_level_test'),
    ]

    operations = [
        migrations.AddField(
            model_name='classrequest',
            name='payment_method',
            field=models.CharField(blank=True, choices=[('cash', 'نقدی'), ('card_to_card', 'کارت به کارت'), ('pos', 'پوز')], max_length=20),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='payment_reference',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='payment_confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
