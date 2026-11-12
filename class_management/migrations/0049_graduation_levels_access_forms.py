from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0048_physicalroom'),
    ]

    operations = [
        migrations.CreateModel(
            name='GraduationLevelSetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('levels', models.JSONField(blank=True, default=dict)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='AccessFormConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('teacher', 'معلم جدید'), ('employee', 'کارمند جدید')], max_length=16, unique=True)),
                ('template_name', models.CharField(blank=True, default='', max_length=255)),
                ('template_b64', models.TextField(blank=True, default='')),
                ('start_row', models.PositiveSmallIntegerField(default=2)),
                ('fields', models.JSONField(blank=True, default=list)),
                ('fixed_cells', models.JSONField(blank=True, default=list)),
                ('letter_template', models.TextField(blank=True, default='')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
