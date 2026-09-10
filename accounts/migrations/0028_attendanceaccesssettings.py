from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('accounts', '0027_alter_menupermission_can_edit_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='AttendanceAccessSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(default='default', max_length=32, unique=True)),
                ('office_attendance_enabled', models.BooleanField(default=True, help_text='ثبت ورود/خروج با QR برای کارمندان و کارشناسان اداری در اپ')),
                ('teacher_attendance_enabled', models.BooleanField(default=True, help_text='ثبت حضور با QR برای استادها در اپ')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='attendance_access_updates', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
