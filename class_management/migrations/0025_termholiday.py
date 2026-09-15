import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0024_classattendance_status'),
    ]

    operations = [
        migrations.CreateModel(
            name='TermHoliday',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(help_text='تاریخ تعطیلی رسمی (میلادی ذخیره می‌شود؛ در پنل شمسی وارد/نمایش می‌شود)')),
                ('description', models.CharField(blank=True, help_text='توضیح تعطیلی، مثلاً «روز طبیعت» یا «تعطیل رسمی»', max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('term', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='holidays', to='class_management.term')),
            ],
            options={
                'ordering': ['date'],
            },
        ),
        migrations.AddConstraint(
            model_name='termholiday',
            constraint=models.UniqueConstraint(fields=('term', 'date'), name='unique_holiday_per_term_date'),
        ),
    ]
