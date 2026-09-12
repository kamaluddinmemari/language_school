from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('accounts', '0029_appaccesssettings'),
    ]

    operations = [
        migrations.CreateModel(
            name='MobileMenuVisibility',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(default='default', max_length=32, unique=True)),
                ('hidden_keys', models.JSONField(blank=True, default=list, help_text='لیست کلیدهای دکمه\u200cهایی که باید مخفی شوند')),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='mobile_menu_visibility_updates', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
