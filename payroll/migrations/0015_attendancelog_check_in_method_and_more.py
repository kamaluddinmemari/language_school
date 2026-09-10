from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('payroll', '0014_officeqrtoken'),
    ]

    operations = [
        migrations.AddField(
            model_name='attendancelog',
            name='check_in_method',
            field=models.CharField(blank=True, choices=[('manual', 'دکمه'), ('qr', 'QR')], help_text='با دکمه\u200cی داشبورد ثبت شده یا با اسکن QR', max_length=10),
        ),
        migrations.AddField(
            model_name='attendancelog',
            name='check_out_method',
            field=models.CharField(blank=True, choices=[('manual', 'دکمه'), ('qr', 'QR')], help_text='با دکمه\u200cی داشبورد ثبت شده یا با اسکن QR', max_length=10),
        ),
    ]
