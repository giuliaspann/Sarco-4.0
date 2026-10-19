"""Righe del display della pesa a fine turno (dalle foto del gruppo Produzione e Qualità)."""

from django.db import migrations

PRODOTTI = [
    ('A', 'Misto Imp. 1', 'IMP1', 'PRODOTTO'),
    ('B', 'Mezzobianco', 'IMP1', 'PRODOTTO'),
    ('C', 'Granella', 'IMP1', 'PRODOTTO'),
    ('D', 'Ferro', 'IMP1', 'RECUPERO'),
    ('E+', 'Zigzag', 'IMP1', 'PRODOTTO'),
    ('E-', 'Barrotti', 'IMP1', 'SCARTO'),
    ('F', 'Scarto', 'IMP1', 'SCARTO'),
    ('G', 'Impianto 2', 'IMP2', 'PRODOTTO'),
    ('I', 'Bianco', 'IMP2', 'PRODOTTO'),
    ('J', 'Mezzobianco', 'IMP2', 'PRODOTTO'),
    ('K', 'Sottovaglio', 'IMP2', 'SCARTO'),
    ('L', 'Incolore', 'IMP2', 'PRODOTTO'),
    ('M', 'Scartobox 1', 'IMP2', 'SCARTO'),
]


def carica(apps, schema_editor):
    P = apps.get_model('turni', 'ProdottoProduzione')
    if P.objects.exists():
        return
    for i, (codice, nome, impianto, categoria) in enumerate(PRODOTTI):
        P.objects.create(codice=codice, nome=nome, impianto=impianto, categoria=categoria, ordine=i)


class Migration(migrations.Migration):
    dependencies = [('turni', '0025_produzione')]
    operations = [migrations.RunPython(carica, migrations.RunPython.noop)]
