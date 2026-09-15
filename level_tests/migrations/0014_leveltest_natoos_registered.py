from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('level_tests', '0013_standardlevel_book_standardlevel_final_units_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='leveltest',
            name='natoos_registered',
            field=models.BooleanField(default=False, help_text='آیا این تعیین سطح در سامانه\u200cی ناتوس هم ثبت شده است'),
        ),
    ]
