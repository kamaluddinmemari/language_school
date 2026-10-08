from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('class_management', '0030_classslotenrollment_carryover_tracking'),
        ('leads', '0017_claims_settled_and_unregistered_claims'),
    ]

    operations = [
        migrations.AddField(
            model_name='debtor',
            name='student',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='debtor',
            name='awaiting_registration',
            field=models.BooleanField(default=False, help_text='دانش‌آموز انتقالی از ترم قبل — در دست بررسی و منتظر ثبت‌نام'),
        ),
        migrations.AddField(
            model_name='debtor',
            name='carried_from_term',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='class_management.term'),
        ),
        migrations.AddField(
            model_name='debtor',
            name='source_slot',
            field=models.ForeignKey(blank=True, help_text='کلاس ترم جدیدی که اسم فرد در آن به‌صورت خاکستری آمده است', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='class_management.classslot'),
        ),
    ]
