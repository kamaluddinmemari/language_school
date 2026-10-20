from django.db import migrations, models


def copy_latest_followup_notes(apps, schema_editor):
    db = schema_editor.connection.alias
    Student = apps.get_model('leads', 'UnregisteredStudent')
    StudentFollowup = apps.get_model('leads', 'UnregisteredStudentFollowup')
    Debtor = apps.get_model('leads', 'Debtor')
    DebtorFollowup = apps.get_model('leads', 'DebtorFollowup')

    for row in Student.objects.using(db).all().iterator():
        followups = StudentFollowup.objects.using(db).filter(student_id=row.pk)
        note = followups.exclude(note='').order_by('-followed_up_at', '-id').values_list('note', flat=True).first()
        if note:
            Student.objects.using(db).filter(pk=row.pk).update(row_description=note)
            # نگه‌داشتن رکوردهای زمان/پیگیر، ولی انتقال متنِ دکمهٔ توضیحات از تاریخچه به ردیف.
            followups.exclude(note='').update(note='')

    for row in Debtor.objects.using(db).all().iterator():
        followups = DebtorFollowup.objects.using(db).filter(debtor_id=row.pk)
        note = followups.exclude(note='').order_by('-followed_up_at', '-id').values_list('note', flat=True).first()
        if note:
            Debtor.objects.using(db).filter(pk=row.pk).update(row_description=note)
            followups.exclude(note='').update(note='')


class Migration(migrations.Migration):
    dependencies = [
        ('leads', '0028_unregisteredstudent_reported_slot'),
    ]

    operations = [
        migrations.AddField(
            model_name='unregisteredstudent',
            name='row_description',
            field=models.TextField(blank=True, default='', help_text='توضیح قابل ویرایش برای نمایش در ردیف پیگیری'),
        ),
        migrations.AddField(
            model_name='debtor',
            name='row_description',
            field=models.TextField(blank=True, default='', help_text='توضیح قابل ویرایش برای نمایش در ردیف پیگیری'),
        ),
        migrations.RunPython(copy_latest_followup_notes, migrations.RunPython.noop),
    ]
