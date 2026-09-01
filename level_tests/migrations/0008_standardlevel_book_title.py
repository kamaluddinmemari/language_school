from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('level_tests', '0007_leveltest_meeting_link_leveltest_mode_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='standardlevel',
            name='book_title',
            field=models.CharField(blank=True, default='', help_text='عنوان کتاب اصلی این سطح', max_length=200),
        ),
    ]
