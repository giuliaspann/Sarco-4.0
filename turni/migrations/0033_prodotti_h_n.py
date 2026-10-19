"""Righe H (Misto) e N (Scartobox 2) del display dell'Impianto 2, viste nelle foto del gruppo."""

from django.db import migrations

ORDINE_IMP2 = ['G', 'H', 'I', 'J', 'K', 'L', 'M', 'N']


def carica(apps, schema_editor):
    P = apps.get_model('turni', 'ProdottoProduzione')
    if not P.objects.exists():
        return
    P.objects.get_or_create(codice='H', impianto='IMP2', defaults={'nome': 'Misto', 'categoria': 'PRODOTTO'})
    P.objects.get_or_create(codice='N', impianto='IMP2', defaults={'nome': 'Scartobox 2', 'categoria': 'SCARTO'})
    for i, codice in enumerate(ORDINE_IMP2):
        P.objects.filter(impianto='IMP2', codice=codice).update(ordine=7 + i)


class Migration(migrations.Migration):
    dependencies = [('turni', '0032_analisi_prodotto')]
    operations = [migrations.RunPython(carica, migrations.RunPython.noop)]
