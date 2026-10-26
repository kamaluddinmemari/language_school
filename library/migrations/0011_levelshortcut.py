from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('library', '0010_alter_book_options_book_sort_order')]
    operations = [migrations.CreateModel(
        name='LevelShortcut',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('level', models.CharField(help_text='نام سطح، مثل teen1 یا 103', max_length=80, unique=True)),
            ('label', models.CharField(blank=True, help_text='عنوان نمایشی میانبر', max_length=80)),
            ('terms_covered', models.PositiveIntegerField(default=1, help_text='این کتاب چند ترم این سطح را پوشش می‌دهد')),
            ('hotkey', models.CharField(blank=True, help_text='کلید میانبر سطح', max_length=40)),
            ('order', models.PositiveIntegerField(default=0)),
            ('created_at', models.DateTimeField(auto_now_add=True)),
            ('book', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='level_shortcuts', to='library.book')),
        ],
        options={'ordering': ['order', 'id']},
    )]
