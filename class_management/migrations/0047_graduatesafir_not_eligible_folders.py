from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('class_management', '0046_graduatesafirarchive_sent_status')]

    operations = [
        migrations.AddField(
            model_name='graduatesafirarchivefolder',
            name='folder_type',
            field=models.CharField(choices=[('safir', 'فرم استاندارد سفیر'), ('not_eligible', 'عدم احراز شرایط')], default='safir', max_length=20),
        ),
        migrations.RemoveConstraint(
            model_name='graduatesafirarchivefolder',
            name='unique_graduate_safir_folder_name',
        ),
        migrations.AddConstraint(
            model_name='graduatesafirarchivefolder',
            constraint=models.UniqueConstraint(fields=('term', 'folder_type', 'parent', 'name'), name='unique_graduate_archive_folder_name_by_type'),
        ),
        migrations.AddField(
            model_name='graduatedstudentinfo',
            name='not_eligible_folder',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='not_eligible_records', to='class_management.graduatesafirarchivefolder'),
        ),
    ]
