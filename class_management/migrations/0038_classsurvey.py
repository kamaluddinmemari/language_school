from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from accounts.archive import keep_current_term_records


class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0037_keep_current_term_records_on_student_delete'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ClassSurveyList',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('percentage', models.PositiveSmallIntegerField(default=20)),
                ('rows', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('term', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='class_survey_lists', to='class_management.term')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='ClassSurveyQuestion',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('age_group', models.CharField(choices=[('all', 'همه'), ('kids', 'کودک'), ('teen', 'نوجوان'), ('adult', 'بزرگسال')], default='all', max_length=10)),
                ('text', models.CharField(max_length=500)),
                ('sort_order', models.PositiveSmallIntegerField(default=0)),
                ('active', models.BooleanField(default=True)),
            ],
            options={'ordering': ['age_group', 'sort_order', 'id']},
        ),
        migrations.CreateModel(
            name='ClassSurveyResponse',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('answers', models.JSONField(blank=True, default=dict)),
                ('completed', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assigned_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('class_slot', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='class_management.classslot')),
                ('student', models.ForeignKey(on_delete=keep_current_term_records, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('survey_list', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='responses', to='class_management.classsurveylist')),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('survey_list', 'student', 'class_slot'), name='unique_survey_response_row')]},
        ),
    ]
