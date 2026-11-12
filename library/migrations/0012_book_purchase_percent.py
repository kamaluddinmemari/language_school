from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0011_levelshortcut'),
    ]

    operations = [
        migrations.AddField(
            model_name='book',
            name='purchase_percent',
            field=models.PositiveSmallIntegerField(default=100, help_text='خرید کتاب برای چند درصد از دانشجویان کلاس/سطح؛ ۱۰۰ = همه'),
        ),
    ]
