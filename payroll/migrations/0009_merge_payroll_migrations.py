from django.db import migrations


class Migration(migrations.Migration):
    """Merge the legacy 0007 branch with 0008_salaryprofile_payroll_thresholds."""

    dependencies = [
        ('payroll', '0007_salaryprofile_leave_hours_and_request_shift'),
        ('payroll', '0008_salaryprofile_payroll_thresholds'),
    ]

    operations = []
