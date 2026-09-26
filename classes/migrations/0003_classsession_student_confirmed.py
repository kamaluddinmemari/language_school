from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('classes', '0002_alter_classsession_id'),
    ]
    operations = [
        migrations.AddField(
            model_name='classsession',
            name='student_confirmed',
            field=models.BooleanField(default=False),
        ),
    ]
