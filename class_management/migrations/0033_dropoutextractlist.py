from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0032_dropoutextractfollowup'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DropoutExtractList',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('mode', models.CharField(default='pair', max_length=16)),
                ('meta', models.JSONField(blank=True, default=dict)),
                ('rows', models.JSONField(blank=True, default=list)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('term', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dropout_extract_lists', to='class_management.term')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddField(
            model_name='dropoutextractfollowup',
            name='saved_list',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='followups', to='class_management.dropoutextractlist'),
        ),
        migrations.RemoveConstraint(
            model_name='dropoutextractfollowup',
            name='uniq_dropout_extract_followup',
        ),
        migrations.AddConstraint(
            model_name='dropoutextractfollowup',
            constraint=models.UniqueConstraint(condition=models.Q(('saved_list__isnull', True)), fields=('national_code', 'term', 'mode'), name='uniq_dropout_extract_followup'),
        ),
        migrations.AddConstraint(
            model_name='dropoutextractfollowup',
            constraint=models.UniqueConstraint(condition=models.Q(('saved_list__isnull', False)), fields=('national_code', 'saved_list'), name='uniq_dropout_extract_followup_list'),
        ),
    ]
