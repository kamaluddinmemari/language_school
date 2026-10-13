from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0031_remove_classattendance_unique_attendance_slot_per_day_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DropoutExtractFollowUp',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('national_code', models.CharField(db_index=True, max_length=10)),
                ('mode', models.CharField(default='pair', max_length=16)),
                ('contacted', models.BooleanField(default=False)),
                ('contacted_at', models.DateTimeField(blank=True, null=True)),
                ('note', models.TextField(blank=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assigned_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('term', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dropout_extract_followups', to='class_management.term')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name='dropoutextractfollowup',
            constraint=models.UniqueConstraint(fields=('national_code', 'term', 'mode'), name='uniq_dropout_extract_followup'),
        ),
    ]
