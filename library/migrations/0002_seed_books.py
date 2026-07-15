from django.db import migrations


def seed_books(apps, schema_editor):
    Book = apps.get_model('library', 'Book')

    titles = []
    titles.append(('Supermind Starter', 'kids'))
    for i in range(1, 6):
        titles.append((f'Supermind {i}', 'kids'))
    for i in range(1, 6):
        titles.append((f'Project {i}', 'teen'))
    for i in range(1, 7):
        titles.append((f'Evolve {i}', 'adult'))
    titles.append(('Oxford Elementary', 'oxford'))
    titles.append(('Oxford Intermediate', 'oxford'))
    titles.append(('Oxford Advance', 'oxford'))
    titles.append(('Mr Bugs', 'other'))

    for title, category in titles:
        Book.objects.get_or_create(title=title, defaults={'category': category})


def unseed_books(apps, schema_editor):
    Book = apps.get_model('library', 'Book')
    Book.objects.filter(current_stock=0, unit_price=0, predicted_students=0).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_books, unseed_books),
    ]
