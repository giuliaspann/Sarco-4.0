"""Si riparte da zero con le notifiche (Giulia, 25/11/2026, giorno del lancio): una volta sola si cancellano
tutte le notifiche del campanello registrate fino alla pubblicazione. Chat, turni, richieste, pulizie e le
iscrizioni dei telefoni alle notifiche non si toccano."""

from django.db import migrations


def azzera(apps, schema_editor):
    Notifica = apps.get_model('turni', 'Notifica')
    n, _ = Notifica.objects.all().delete()
    print(f'\n  Notifiche cancellate: {n}')


class Migration(migrations.Migration):
    dependencies = [('turni', '0090_resp_impianto_come_ufficio')]

    operations = [migrations.RunPython(azzera, migrations.RunPython.noop)]
