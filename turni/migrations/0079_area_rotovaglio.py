from django.db import migrations


def applica_file(apps, schema_editor):
    """File «Regole Pulizie - unico.xlsx» del 22/11/2026: la pulizia «Rotovaglio» si chiama «Area Rotovaglio»."""
    from turni.regole_pulizie import applica

    applica(apps.get_model('turni', 'ElementoPulizia'), apps.get_model('turni', 'RegolaPulizia'))


class Migration(migrations.Migration):
    dependencies = [('turni', '0078_regole_file_unico')]
    operations = [migrations.RunPython(applica_file, migrations.RunPython.noop)]
