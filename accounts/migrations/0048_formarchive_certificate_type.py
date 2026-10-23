from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0047_archived_student_keep_records'),
    ]

    operations = [
        migrations.AlterField(
            model_name='formarchive',
            name='document_type',
            field=models.CharField(
                choices=[('disciplinary', 'تعهد انضباطی'), ('refund', 'استرداد'), ('certificate', 'گواهی اشتغال به تحصیل')],
                max_length=20,
            ),
        ),
    ]
