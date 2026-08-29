from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('leads', '0008_unregistered_level_identity'),
        ('class_management', '0015_merge_20260827_1625'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DropoutFollowup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('followed_up_at', models.DateTimeField(auto_now_add=True)),
                ('note', models.CharField(blank=True, max_length=500)),
                ('followed_up_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('from_term', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='class_management.term')),
                ('student', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='dropout_followups', to=settings.AUTH_USER_MODEL)),
                ('to_term', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='class_management.term')),
            ],
            options={'ordering': ['-followed_up_at']},
        ),
    ]
