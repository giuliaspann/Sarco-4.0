from django.db import migrations


def visti_approvati(apps, schema_editor):
    # gli avvisi che l'ufficio aveva già segnato come visti valgono come approvati (Giulia, 11/11/2026)
    AvvisoAssenza = apps.get_model('turni', 'AvvisoAssenza')
    AvvisoAssenza.objects.filter(visto_il__isnull=False, esito='').update(esito='approvato')


class Migration(migrations.Migration):
    dependencies = [('turni', '0068_anagrafica_convalide')]
    operations = [migrations.RunPython(visti_approvati, migrations.RunPython.noop)]
