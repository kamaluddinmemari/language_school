from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0048_formarchive_certificate_type'),
    ]

    operations = [
        migrations.AlterField(
            model_name='formarchive',
            name='document_type',
            field=models.CharField(
                choices=[
                    ('disciplinary', 'تعهد انضباطی'),
                    ('refund', 'استرداد'),
                    ('certificate', 'گواهی اشتغال به تحصیل'),
                    ('employee_certificate', 'گواهی اشتغال به کار کارکنان'),
                ],
                max_length=20,
            ),
        ),
    ]
