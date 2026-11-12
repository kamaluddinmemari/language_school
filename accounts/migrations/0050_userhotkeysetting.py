from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0049_formarchive_employee_certificate_type'),
    ]

    operations = [
        migrations.CreateModel(
            name='UserHotkeySetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('hotkeys', models.JSONField(blank=True, default=list)),
                ('toast_enabled', models.BooleanField(default=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='hotkey_setting', to='accounts.user')),
            ],
        ),
    ]
