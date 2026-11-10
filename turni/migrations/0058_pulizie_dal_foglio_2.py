from django.db import migrations


def avanti(apps, schema_editor):
    from turni.regole_foglio import applica

    applica(apps.get_model('turni', 'ElementoPulizia'), apps.get_model('turni', 'RegolaPulizia'))


class Migration(migrations.Migration):
    """Di nuovo le regole del foglio: convalida "Capo Turno, poi responsabile piazzale" e macchine ottiche al manutentore."""

    dependencies = [
        ('turni', '0057_convalida_ct_poi_rp'),
    ]

    operations = [
        migrations.RunPython(avanti, migrations.RunPython.noop),
    ]
