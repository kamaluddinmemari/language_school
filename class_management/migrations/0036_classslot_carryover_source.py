from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0035_dropoutextractfollowup_not_coming'),
    ]

    operations = [
        migrations.AddField(
            model_name='classslot',
            name='carried_from_slot',
            field=models.ForeignKey(
                blank=True,
                help_text='کلاس مبدأ هنگام انتقال به ترم بعد',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='next_term_copies',
                to='class_management.classslot',
            ),
        ),
        migrations.AddField(
            model_name='classslot',
            name='carry_students_from_source',
            field=models.BooleanField(default=True, help_text='آیا زبان‌آموزان کلاس مبدأ به این کلاس منتقل شوند'),
        ),
    ]
