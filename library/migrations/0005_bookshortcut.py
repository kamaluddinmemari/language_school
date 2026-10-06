from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0004_alter_book_category'),
    ]

    operations = [
        migrations.CreateModel(
            name='BookShortcut',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label', models.CharField(blank=True, help_text='عنوان دکمه؛ اگر خالی باشد نام کتاب نمایش داده می‌شود', max_length=80)),
                ('default_quantity', models.PositiveIntegerField(default=1)),
                ('order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('book', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shortcuts', to='library.book')),
            ],
            options={'ordering': ['order', 'id']},
        ),
    ]
