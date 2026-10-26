from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0040_classsurvey_selected_classes'),
    ]

    operations = [
        migrations.AddField(
            model_name='term',
            name='pre_registration_start',
            field=models.DateField(blank=True, null=True, help_text='تاریخ شروع پیش‌ثبت‌نام این ترم؛ از همین تاریخ و به‌مدت یک هفته، این ترم «ترم جاری» حساب می‌شود (معیار اصلی انتخاب ترم)'),
        ),
        migrations.CreateModel(
            name='TermSetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('force_latest_term', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
