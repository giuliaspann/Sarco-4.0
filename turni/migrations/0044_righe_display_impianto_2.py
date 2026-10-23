"""Righe dell'Impianto 2 come sul display della pesa (foto del 21/10/2026): L-SCARTO1, M-SCARTO2, niente N."""

from django.db import migrations


def allinea(apps, schema_editor):
    P = apps.get_model('turni', 'ProdottoProduzione')
    R = apps.get_model('turni', 'RigaProduzione')
    P.objects.filter(impianto='IMP2', codice='L').update(nome='Scarto 1', categoria='SCARTO')
    P.objects.filter(impianto='IMP2', codice='M').update(nome='Scarto 2', categoria='SCARTO')
    # la riga N non esiste sul display: si toglie, ma se ha già dati salvati si nasconde soltanto
    for n in P.objects.filter(impianto='IMP2', codice='N'):
        if R.objects.filter(prodotto=n).exists():
            n.attivo = False
            n.save(update_fields=['attivo'])
        else:
            n.delete()


class Migration(migrations.Migration):
    dependencies = [('turni', '0043_elenco_attrezzature_mezzi')]
    operations = [migrations.RunPython(allinea, migrations.RunPython.noop)]
