from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0006_bookshortcut_hotkey'),
    ]

    operations = [
        migrations.AlterField(
            model_name='bookshortcut',
            name='hotkey',
            field=models.CharField(blank=True, help_text='کلید میانبر کیبرد (یک یا دو کلید پشت‌سرهم)، مثل Digit1 یا Digit1,Digit2 یا Alt+KeyA', max_length=40),
        ),
    ]
