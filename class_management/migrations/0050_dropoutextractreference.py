from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0049_graduation_levels_access_forms'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name='DropoutExtractReference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('saved_list', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='reference_for_terms', to='class_management.dropoutextractlist')),
                ('selected_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('term', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='dropout_extract_reference', to='class_management.term')),
            ],
        ),
    ]
