from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('class_management', '0047_graduatesafir_not_eligible_folders')]

    operations = [
        migrations.CreateModel(
            name='PhysicalRoom',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.PositiveIntegerField(unique=True)),
                ('seats', models.PositiveIntegerField(default=15, help_text='تعداد صندلی فیزیکی این اتاق')),
                ('is_active', models.BooleanField(default=True, help_text='اتاق فعلاً در دسترس است؟')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={'ordering': ['number']},
        ),
    ]
