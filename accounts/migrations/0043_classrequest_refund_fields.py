import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0042_classrequest_teacher_assigned_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='classrequest', name='is_refunded',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='classrequest', name='refund_amount',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='classrequest', name='refund_date',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='classrequest', name='refund_reference',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='classrequest', name='refund_note',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='classrequest', name='refund_recorded_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='recorded_class_refunds', to='accounts.user'),
        ),
    ]
