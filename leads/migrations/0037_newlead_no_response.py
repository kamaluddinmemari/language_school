from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('leads', '0036_employee_followup_assigned_employees'),
    ]

    operations = [
        migrations.AddField(
            model_name='newlead',
            name='no_response',
            field=models.BooleanField(default=False, help_text='کارمند برای تماس با این فرد پاسخ دریافت نکرده است'),
        ),
    ]
