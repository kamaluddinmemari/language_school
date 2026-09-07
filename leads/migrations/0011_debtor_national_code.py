from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('leads', '0010_unregisteredstudent_class_slot')]
    operations = [migrations.AddField(model_name='debtor', name='national_code', field=models.CharField(blank=True, max_length=20))]
