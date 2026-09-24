# Generated manually (no network access to run makemigrations in this environment).
# خواسته: در فرم ثبت نتیجه‌ی تعیین سطح، به‌جای تاریخ/ساعتِ آزمون — انتخاب یکی از کلاس‌های
# موجودِ همان سطح (روز/ساعت/استاد)، و تیک نیاز به کلاس خصوصی/جبرانی + تعداد جلسه.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('level_tests', '0015_leveltest_reminders'),
        ('class_management', '0028_classslot_friday_morning_evening'),
    ]

    operations = [
        migrations.AddField(
            model_name='leveltest',
            name='assigned_class_slot',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='level_test_placements', to='class_management.classslot'),
        ),
        migrations.AddField(
            model_name='leveltest',
            name='assigned_class_day',
            field=models.CharField(blank=True, help_text='عکسِ روز برگزاری کلاسِ انتخاب‌شده، در لحظه‌ی ثبت نتیجه', max_length=100),
        ),
        migrations.AddField(
            model_name='leveltest',
            name='assigned_class_time',
            field=models.CharField(blank=True, help_text='عکسِ ساعت برگزاری کلاسِ انتخاب‌شده، در لحظه‌ی ثبت نتیجه', max_length=20),
        ),
        migrations.AddField(
            model_name='leveltest',
            name='assigned_class_teacher_name',
            field=models.CharField(blank=True, help_text='عکسِ نام استادِ کلاسِ انتخاب‌شده، در لحظه‌ی ثبت نتیجه', max_length=150),
        ),
        migrations.AddField(
            model_name='leveltest',
            name='needs_private_class',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='leveltest',
            name='private_sessions_needed',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='leveltest',
            name='needs_makeup_class',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='leveltest',
            name='makeup_sessions_needed',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
