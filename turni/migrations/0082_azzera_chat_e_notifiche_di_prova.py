"""Chat e notifiche pulite per il lancio (Giulia, 23/11/2026).

Fino a oggi l'app è stata usata solo per le prove: si cancellano una volta sola tutti i messaggi delle chat
(con foto, video, documenti, sondaggi, reazioni e «chi l'ha letto»), le letture delle chat e tutte le
notifiche del centro notifiche. La Bacheca non si tocca.
"""

from django.db import migrations


def azzera(apps, schema_editor):
    MessaggioChat = apps.get_model('turni', 'MessaggioChat')
    LetturaChat = apps.get_model('turni', 'LetturaChat')
    Notifica = apps.get_model('turni', 'Notifica')
    # i file sul disco (se il disco è raggiungibile da qui: altrimenti restano, ma nessuno li vede più)
    for m in MessaggioChat.objects.all().iterator():
        for campo in (m.foto, m.video, m.documento):
            if campo:
                try:
                    campo.storage.delete(campo.name)
                except Exception:
                    pass
    # le risposte puntano ad altri messaggi: prima si staccano, poi si cancella tutto (sondaggi, voti,
    # reazioni e viste se ne vanno insieme ai messaggi)
    MessaggioChat.objects.update(risposta_a=None)
    n_msg = MessaggioChat.objects.count()
    MessaggioChat.objects.all().delete()
    LetturaChat.objects.all().delete()
    n_not = Notifica.objects.count()
    Notifica.objects.all().delete()
    print(f'\n  Cancellati {n_msg} messaggi di chat e {n_not} notifiche di prova.')


class Migration(migrations.Migration):
    dependencies = [('turni', '0081_chat_video_risposte_reazioni')]

    operations = [migrations.RunPython(azzera, migrations.RunPython.noop)]
