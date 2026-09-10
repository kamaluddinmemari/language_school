from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('accounts', '0028_attendanceaccesssettings'),
    ]

    operations = [
        migrations.CreateModel(
            name='AppAccessSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(default='default', max_length=32, unique=True)),
                ('teacher_app_enabled', models.BooleanField(default=True, help_text='اپ استاد (teacher و evaluator)')),
                ('student_app_enabled', models.BooleanField(default=True, help_text='اپ دانش\u200cآموز')),
                ('office_app_enabled', models.BooleanField(default=True, help_text='اپ اداری (office و employee)')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='app_access_updates', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
