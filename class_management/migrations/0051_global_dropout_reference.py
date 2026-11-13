from django.db import migrations, models


def keep_single_global_reference(apps, schema_editor):
    Reference = apps.get_model('class_management', 'DropoutExtractReference')
    refs = list(Reference.objects.select_related('term').order_by('term__year', 'term__term_number', 'pk'))
    if not refs:
        return
    anchor_refs = [ref for ref in refs if ref.term.term_number == 6]
    keep = anchor_refs[0] if anchor_refs else refs[0]
    Reference.objects.exclude(pk=keep.pk).delete()
    Reference.objects.filter(pk=keep.pk).update(scope='global')


class Migration(migrations.Migration):
    dependencies = [
        ('class_management', '0050_dropoutextractreference'),
    ]
    operations = [
        migrations.AddField(
            model_name='dropoutextractreference',
            name='scope',
            field=models.CharField(blank=True, max_length=16, null=True),
        ),
        migrations.RunPython(keep_single_global_reference, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='dropoutextractreference',
            name='scope',
            field=models.CharField(default='global', editable=False, max_length=16, unique=True),
        ),
    ]
