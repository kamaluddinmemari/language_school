import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('level_tests', '0013_standardlevel_book_standardlevel_final_units_and_more'),
        ('leads', '0011_debtor_national_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='newlead',
            name='needs_level_test',
            field=models.BooleanField(default=False, help_text='این فرد نیاز به تعیین سطح دارد — با تیک\u200cخوردن، یک وقت تعیین سطح برایش رزرو و در صف تعیین سطح ثبت می\u200cشود'),
        ),
        migrations.AddField(
            model_name='newlead',
            name='level_test',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='source_lead', to='level_tests.leveltest'),
        ),
    ]
