from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('leads', '0040_unregisteredstudent_attendance_transfer'),
    ]

    operations = [
        migrations.AlterField(
            model_name='unregisteredstudent',
            name='attendance_transfer',
            field=models.CharField(
                blank=True, default='', max_length=14,
                choices=[('', 'خیر'), ('attending', 'در کلاس حضور دارد'), ('not_in_class', 'اصلاً در این کلاس نیست'), ('never_came', 'کلاً نیامده')],
                help_text='اگر از دکمه‌های حضور و غیابِ اپ به پیگیری منتقل شده باشد، نوع انتقال',
            ),
        ),
        migrations.AddField(
            model_name='unregisteredstudent',
            name='relocation_note',
            field=models.TextField(blank=True, default='', help_text='توضیح جابجایی (کلاس قدیمی ← کلاس درست) — زرد'),
        ),
        migrations.CreateModel(
            name='FollowupAlertEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('never_came', 'کلاً نیامده'), ('found_elsewhere', 'در کلاس دیگر پیدا شد')], max_length=20)),
                ('name', models.CharField(blank=True, default='', max_length=200)),
                ('text', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('unregistered', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='alert_events', to='leads.unregisteredstudent')),
            ],
            options={'ordering': ['id']},
        ),
    ]
