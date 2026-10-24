from django.db import migrations, models

TYPES = ['unregistered', 'debtors', 'waiting-list', 'consecutive-dropouts', 'class-survey']


def split_shared_rules(apps, schema_editor):
    """ددلاین مشترک قبلی را برای هر پنج نوع پیگیری کپی می‌کند تا رفتار فعلی تغییر ناگهانی نکند."""
    Rule = apps.get_model('leads', 'EmployeeFollowupDeadlineRule')
    for rule in list(Rule.objects.filter(followup_type='unregistered')):
        for kind in TYPES[1:]:
            Rule.objects.get_or_create(term_id=rule.term_id, followup_type=kind, defaults={
                'enabled': rule.enabled, 'mode': rule.mode, 'deadline_date': rule.deadline_date,
                'deadline_time': rule.deadline_time, 'deadline_week': rule.deadline_week,
                'updated_by_id': rule.updated_by_id,
            })


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0033_employeefollowupdeadlinerule'),
    ]

    operations = [
        migrations.AddField(
            model_name='employeefollowupdeadlinerule',
            name='followup_type',
            field=models.CharField(
                choices=[('unregistered', 'پیگیری افراد ثبت‌نام‌نشده'), ('debtors', 'پیگیری بدهکاران'),
                         ('waiting-list', 'پیگیری لیست انتظار'), ('consecutive-dropouts', 'پیگیری ریزشی‌های دو ترم متوالی'),
                         ('class-survey', 'پیگیری نظرسنجی کلاس‌ها')],
                default='unregistered', max_length=30),
        ),
        migrations.RemoveConstraint(model_name='employeefollowupdeadlinerule', name='unique_employee_followup_deadline_per_term'),
        migrations.AddConstraint(
            model_name='employeefollowupdeadlinerule',
            constraint=models.UniqueConstraint(fields=('term', 'followup_type'), name='unique_employee_followup_deadline_per_term_type'),
        ),
        migrations.RunPython(split_shared_rules, migrations.RunPython.noop),
    ]
