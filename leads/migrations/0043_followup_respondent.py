from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('leads', '0042_followup_contacted')]

    operations = [
        migrations.AddField(
            model_name='unregisteredstudent', name='respondent',
            field=models.CharField(blank=True, choices=[('self', 'خود فرد'), ('father', 'پدر'), ('mother', 'مادر')], default='', help_text='فرد پاسخ‌گو در تماس', max_length=10),
        ),
        migrations.AddField(
            model_name='debtor', name='respondent',
            field=models.CharField(blank=True, choices=[('self', 'خود فرد'), ('father', 'پدر'), ('mother', 'مادر')], default='', help_text='فرد پاسخ‌گو در تماس', max_length=10),
        ),
    ]
