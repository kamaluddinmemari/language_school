from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0023_alter_appearancesettings_id'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='role',
            field=models.CharField(
                choices=[
                    ('admin', 'مدیر'),
                    ('teacher', 'معلم'),
                    ('student', 'دانش‌آموز'),
                    ('evaluator', 'کارشناس آموزش'),
                    ('office', 'کارشناس اداری'),
                    ('employee', 'کارمند'),
                ],
                default='student',
                max_length=10,
            ),
        ),
        migrations.CreateModel(
            name='MenuPermission',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('role', models.CharField(
                    choices=[
                        ('employee', 'employee'),
                        ('office', 'office'),
                        ('evaluator', 'evaluator'),
                    ],
                    max_length=15,
                )),
                ('menu_key', models.CharField(max_length=40)),
                ('enabled', models.BooleanField(
                    default=False,
                    help_text='دیدن این منو (نمایش لینک + امکان باز کردن صفحه)',
                )),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'constraints': [
                    models.UniqueConstraint(
                        fields=('role', 'menu_key'),
                        name='unique_role_menu_permission',
                    ),
                ],
            },
        ),
    ]
