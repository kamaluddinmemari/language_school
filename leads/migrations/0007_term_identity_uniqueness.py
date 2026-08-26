from django.db import migrations, models
import django.db.models.deletion


def clear_identity_keys(apps, schema_editor):
    Lead = apps.get_model('leads', 'NewLead')
    Unregistered = apps.get_model('leads', 'UnregisteredStudent')
    Debtor = apps.get_model('leads', 'Debtor')

    def key(obj, include_national=True):
        national = ''.join(str(getattr(obj, 'national_code', '') or '').split()).strip() if include_national else ''
        if national:
            return f'national:{national}'
        phone = ''.join(str(getattr(obj, 'phone', '') or '').split()).strip()
        name = ' '.join(f"{getattr(obj, 'first_name', '') or ''} {getattr(obj, 'last_name', '') or ''}".split()).casefold()
        return f'phone:{phone}|name:{name}' if phone else f'name:{name}'

    for Model, include_national in ((Unregistered, True), (Debtor, False), (Lead, True)):
        seen = set()
        for obj in Model.objects.filter(identity_key='').order_by('id'):
            if not getattr(obj, 'term_id', None):
                continue
            value = key(obj, include_national)
            marker = (obj.term_id, value)
            # Preserve any pre-existing duplicate rows; the backend will block new ones.
            if value and marker not in seen:
                obj.identity_key = value
                obj.save(update_fields=['identity_key'])
                seen.add(marker)


class Migration(migrations.Migration):
    dependencies = [('leads', '0006_debtor_term_unregisteredstudent_term')]
    operations = [
        migrations.AddField(model_name='newlead', name='term', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='class_management.term')),
        migrations.AddField(model_name='newlead', name='identity_key', field=models.CharField(blank=True, default='', editable=False, max_length=255)),
        migrations.AddField(model_name='unregisteredstudent', name='identity_key', field=models.CharField(blank=True, default='', editable=False, max_length=255)),
        migrations.AddField(model_name='debtor', name='identity_key', field=models.CharField(blank=True, default='', editable=False, max_length=255)),
        migrations.RunPython(clear_identity_keys, migrations.RunPython.noop),
        migrations.AddConstraint(model_name='newlead', constraint=models.UniqueConstraint(condition=models.Q(('term__isnull', False), _negated=False) & ~models.Q(('identity_key', ''), _negated=False), fields=('term', 'identity_key'), name='uniq_newlead_term_identity')),
        migrations.AddConstraint(model_name='unregisteredstudent', constraint=models.UniqueConstraint(condition=models.Q(('term__isnull', False), _negated=False) & ~models.Q(('identity_key', ''), _negated=False), fields=('term', 'identity_key'), name='uniq_unregistered_term_identity')),
        migrations.AddConstraint(model_name='debtor', constraint=models.UniqueConstraint(condition=models.Q(('term__isnull', False), _negated=False) & ~models.Q(('identity_key', ''), _negated=False), fields=('term', 'identity_key'), name='uniq_debtor_term_identity')),
    ]
