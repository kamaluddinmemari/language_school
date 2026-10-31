from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0045_graduatedstudent_not_eligible'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='GraduateSafirArchive',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('term_title', models.CharField(blank=True, max_length=200)),
                ('filename', models.CharField(max_length=300)),
                ('row_count', models.PositiveIntegerField(default=0)),
                ('rows', models.JSONField(default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('sent_to_center', models.BooleanField(default=False)),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('term', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='graduate_safir_archives', to='class_management.term')),
            ],
            options={'ordering': ['-created_at', '-id']},
        ),
        migrations.CreateModel(
            name='GraduateSafirArchiveFolder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('parent', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='children', to='class_management.graduatesafirarchivefolder')),
                ('term', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='graduate_safir_archive_folders', to='class_management.term')),
            ],
            options={'ordering': ['name', 'id']},
        ),
        migrations.AddConstraint(
            model_name='graduatesafirarchivefolder',
            constraint=models.UniqueConstraint(fields=('term', 'parent', 'name'), name='unique_graduate_safir_folder_name'),
        ),
        migrations.AddField(
            model_name='graduatesafirarchive',
            name='folder',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='archives', to='class_management.graduatesafirarchivefolder'),
        ),
        migrations.AddField(
            model_name='graduatedstudentinfo',
            name='archive',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='records', to='class_management.graduatesafirarchive'),
        ),
    ]
