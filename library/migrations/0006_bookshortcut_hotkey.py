from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0005_bookshortcut'),
    ]

    operations = [
        migrations.AddField(
            model_name='bookshortcut',
            name='hotkey',
            field=models.CharField(blank=True, help_text='کلید میانبر کیبرد، مثل Digit1 یا Alt+KeyA', max_length=24),
        ),
    ]
