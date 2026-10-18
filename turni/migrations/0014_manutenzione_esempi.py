"""Incarichi di manutenzione dall'organigramma e macchine d'esempio."""

from django.db import migrations


def applica(apps, schema_editor):
    from turni.esempi_manutenzione import carica

    Dipendente = apps.get_model('turni', 'Dipendente')
    Dipendente.objects.filter(nome='MARCHESE LEONARDO').update(resp_manutenzione=True)
    Dipendente.objects.filter(nome='BONOMO MICHELANGELO').update(acquisti=True)
    carica(apps)


class Migration(migrations.Migration):
    dependencies = [('turni', '0013_manutenzione')]
    operations = [migrations.RunPython(applica, migrations.RunPython.noop)]
