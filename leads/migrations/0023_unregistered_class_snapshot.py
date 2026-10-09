from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('leads', '0022_unregisteredstudent_is_misplaced_and_more'),
    ]

    operations = [
        migrations.AddField(model_name='unregisteredstudent', name='class_number', field=models.CharField(blank=True, default='', max_length=30)),
        migrations.AddField(model_name='unregisteredstudent', name='class_teacher', field=models.CharField(blank=True, default='', max_length=150)),
        migrations.AddField(model_name='unregisteredstudent', name='class_time', field=models.CharField(blank=True, default='', max_length=30)),
        migrations.AddField(model_name='unregisteredstudent', name='class_day', field=models.CharField(blank=True, default='', max_length=100)),
    ]
