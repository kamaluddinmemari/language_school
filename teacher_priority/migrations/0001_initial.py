from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name='TeacherPriorityConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(default='default', max_length=32, unique=True)),
                ('w_parity', models.DecimalField(decimal_places=2, default=25, help_text='وزن تنوع برنامه (زوج/فرد)', max_digits=6)),
                ('w_students', models.DecimalField(decimal_places=2, default=25, help_text='وزن تعداد دانش‌آموزان ترم', max_digits=6)),
                ('w_one_day', models.DecimalField(decimal_places=2, default=25, help_text='وزن کلاس‌های یک‌روز در هفته', max_digits=6)),
                ('w_class_count', models.DecimalField(decimal_places=2, default=25, help_text='وزن تعداد کلاس‌های ترم', max_digits=6)),
                ('parity_even_only_ratio', models.DecimalField(decimal_places=2, default='0.55', help_text='نسبت امتیاز «فقط زوج» به وزن تنوع', max_digits=4)),
                ('parity_odd_only_ratio', models.DecimalField(decimal_places=2, default='0.35', help_text='نسبت امتیاز «فقط فرد» به وزن تنوع (باید کمتر از فقط‌زوج باشد)', max_digits=4)),
                ('student_target', models.PositiveIntegerField(default=60, help_text='تعداد دانش‌آموزی که امتیاز کامل معیار دانش‌آموز را می‌دهد')),
                ('class_count_target', models.PositiveIntegerField(default=6, help_text='تعداد کلاسی که امتیاز کامل معیار تعداد کلاس را می‌دهد')),
                ('absence_penalty_per_event', models.DecimalField(decimal_places=2, default=4, help_text='امتیاز منفی هر غیبتِ تاییدشده در ترم', max_digits=5)),
                ('absence_penalty_cap', models.DecimalField(decimal_places=2, default=20, help_text='سقف مجموع امتیاز منفی غیبت در یک ترم', max_digits=5)),
                ('private_session_penalty', models.DecimalField(decimal_places=2, default=3, help_text='کسر امتیاز اولویت به‌ازای هر جلسه‌ی کلاس خصوصی', max_digits=5)),
                ('makeup_session_penalty', models.DecimalField(decimal_places=2, default='1.5', help_text='کسر امتیاز اولویت به‌ازای هر جلسه‌ی کلاس جبرانی (کمتر از خصوصی)', max_digits=5)),
                ('apply_to_hourly_price', models.BooleanField(default=False, help_text='اگر روشن باشد، امتیاز اولویت با ضریب زیر روی قیمت هر جلسه/ساعت استاد اثر می‌گذارد')),
                ('price_coefficient', models.DecimalField(decimal_places=2, default='0.20', help_text='ضریب اثر: قیمت × (۱ + ضریب × امتیاز/۱۰۰). مثلاً ۰٫۲۰ یعنی امتیاز ۱۰۰ = ۲۰٪ افزایش', max_digits=5)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': 'تنظیمات امتیاز اولویت استادها'},
        ),
    ]
