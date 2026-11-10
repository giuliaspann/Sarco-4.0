from django.db import migrations


def avanti(apps, schema_editor):
    from turni.regole_foglio import applica

    applica(apps.get_model('turni', 'ElementoPulizia'), apps.get_model('turni', 'RegolaPulizia'))


class Migration(migrations.Migration):
    """Pulizie e regole dal foglio "Regole Pulizie per Area e Ruolo" del responsabile turni."""

    dependencies = [
        ('turni', '0054_regole_ruolo_rotazione'),
    ]

    operations = [
        migrations.RunPython(avanti, migrations.RunPython.noop),
    ]
