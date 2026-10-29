# Generated manually for persistent graduate information.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0041_term_pre_registration_termsetting'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='GraduatedStudentInfo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('record_key', models.CharField(max_length=100)),
                ('manual', models.BooleanField(default=False)),
                ('first_name', models.CharField(blank=True, max_length=150)),
                ('last_name', models.CharField(blank=True, max_length=150)),
                ('full_name_en', models.CharField(blank=True, max_length=200)),
                ('national_code', models.CharField(blank=True, max_length=32)),
                ('phone', models.CharField(blank=True, max_length=32)),
                ('level', models.CharField(blank=True, max_length=80)),
                ('teacher', models.CharField(blank=True, max_length=200)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('gender', models.CharField(blank=True, max_length=20)),
                ('age_group', models.CharField(blank=True, max_length=20)),
                ('next_term', models.BooleanField(default=False)),
                ('graduation_date', models.DateField(blank=True, null=True)),
                ('previous_term_grade_1', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('previous_term_grade_2', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('previous_term_grade_3', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('average_grade', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('sent_to_center', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('student', models.ForeignKey(blank=True, limit_choices_to={'role': 'student'}, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='graduated_student_records', to=settings.AUTH_USER_MODEL)),
                ('term', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='graduated_student_records', to='class_management.term')),
            ],
            options={
                'ordering': ['last_name', 'first_name', 'id'],
                'constraints': [models.UniqueConstraint(fields=('term', 'record_key'), name='unique_graduate_record_per_term_key')],
            },
        ),
    ]
