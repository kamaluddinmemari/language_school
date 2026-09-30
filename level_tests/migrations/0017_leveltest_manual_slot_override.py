from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('level_tests', '0016_leveltest_class_placement_and_needs'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LevelTestManualSlotOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField()),
                ('time', models.CharField(help_text='ساعت شروعِ بازه\u200cی ۵ دقیقه\u200cای، مثل 09:05', max_length=5)),
                ('state', models.CharField(choices=[('blocked', 'مسدود شده (اشغال دستی)'), ('free', 'باز شده (آزاد دستی)')], max_length=10)),
                ('note', models.CharField(blank=True, max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['date', 'time'], 'unique_together': {('date', 'time')}},
        ),
    ]
