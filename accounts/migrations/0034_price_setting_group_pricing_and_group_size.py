# Generated manually (no network access to run makemigrations in this environment).
# فیلدهای قیمت خصوصی چند نفره (۲نفره/۳نفر‌به‌بالا) و group_size اضافه می‌شوند.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0033_classrequest_group_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='pricesetting',
            name='two_person_one_hour_price',
            field=models.PositiveIntegerField(default=400000, help_text='سهم هرنفر — کلاس خصوصی دقیقاً ۲نفره، یک‌ساعته'),
        ),
        migrations.AddField(
            model_name='pricesetting',
            name='two_person_one_half_hour_price',
            field=models.PositiveIntegerField(default=550000, help_text='سهم هرنفر — کلاس خصوصی دقیقاً ۲نفره، یک‌ونیم‌ساعته'),
        ),
        migrations.AddField(
            model_name='pricesetting',
            name='three_plus_person_one_hour_price',
            field=models.PositiveIntegerField(default=400000, help_text='سهم هرنفر — کلاس خصوصی ۳نفر و بیشتر، یک‌ساعته'),
        ),
        migrations.AddField(
            model_name='pricesetting',
            name='three_plus_person_one_half_hour_price',
            field=models.PositiveIntegerField(default=550000, help_text='سهم هرنفر — کلاس خصوصی ۳نفر و بیشتر، یک‌ونیم‌ساعته'),
        ),
        migrations.AddField(
            model_name='classrequest',
            name='group_size',
            field=models.PositiveSmallIntegerField(default=1),
        ),
    ]
