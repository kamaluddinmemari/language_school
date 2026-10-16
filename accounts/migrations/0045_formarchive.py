# Generated for shared signed-form archives.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0044_classrequest_is_urgent'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='FormArchive',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('document_type', models.CharField(choices=[('disciplinary', 'تعهد انضباطی'), ('refund', 'استرداد')], max_length=20)),
                ('number', models.CharField(max_length=32)),
                ('data', models.JSONField(blank=True, default=dict)),
                ('signed_image', models.ImageField(blank=True, null=True, upload_to='form_archives/%Y/%m/')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='form_archives', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at', '-id'],
                'constraints': [models.UniqueConstraint(fields=('document_type', 'number'), name='uniq_form_archive_type_number')],
            },
        ),
    ]
