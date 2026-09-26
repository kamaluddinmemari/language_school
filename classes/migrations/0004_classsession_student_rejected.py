from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('classes', '0003_classsession_student_confirmed')]
    operations = [migrations.AddField(model_name='classsession', name='student_rejected', field=models.BooleanField(default=False))]
