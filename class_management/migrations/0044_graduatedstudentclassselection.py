from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0043_graduatedstudent_excluded'),
    ]

    operations = [
        migrations.CreateModel(
            name='GraduatedStudentClassSelection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('class_slot', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='graduated_student_class_selections', to='class_management.classslot')),
                ('term', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='graduated_student_class_selections', to='class_management.term')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('term', 'class_slot'), name='unique_graduate_class_selection')],
            },
        ),
    ]
