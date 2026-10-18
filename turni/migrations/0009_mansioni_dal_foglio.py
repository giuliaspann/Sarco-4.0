"""Imposta le mansioni dal foglio dell'ufficio a chi è già nell'elenco dei dipendenti."""

from django.db import migrations


def applica(apps, schema_editor):
    from turni.mansioni import mansione_per

    Dipendente = apps.get_model('turni', 'Dipendente')
    for d in Dipendente.objects.all():
        valore = mansione_per(d.nome)
        if valore and d.mansione != valore:
            d.mansione = valore
            d.save(update_fields=['mansione'])


class Migration(migrations.Migration):
    dependencies = [('turni', '0008_mansioni_multiple')]
    operations = [migrations.RunPython(applica, migrations.RunPython.noop)]
