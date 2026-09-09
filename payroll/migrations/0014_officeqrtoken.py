from django.db import migrations, models
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ('payroll', '0013_employeeprofile_minimum_monthly_hours_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='OfficeQrToken',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['-created_at']},
        ),
    ]
