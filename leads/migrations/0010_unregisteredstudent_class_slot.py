from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('leads', '0009_dropoutfollowup'),
        ('class_management', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='unregisteredstudent',
            name='class_slot',
            field=models.ForeignKey(
                blank=True,
                help_text='کلاسی که این فرد در آن خارج از فهرست رسمی گزارش شده است',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='unregistered_students',
                to='class_management.classslot',
            ),
        ),
    ]
