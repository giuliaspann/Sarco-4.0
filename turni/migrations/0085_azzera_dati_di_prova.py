"""App pulita prima della presentazione e del lancio (Giulia, 23/11/2026).

Fino a oggi l'app è stata usata solo per le prove: si cancellano una volta sola tutti i dati inseriti
(pulizie e avvisi di pulizia, Bacheca, chat e notifiche, ferie, assenze, cambi turno, turni extra, fermi,
produzione, analisi, manutenzione, riunioni, documenti, conversazioni con l'assistente, blocchi d'accesso)
con le loro foto e i loro file, e gli ESEMPI della manutenzione (macchine d'esempio, ricambi, manutenzioni
programmate).

Restano: utenti, dipendenti, turni caricati dai file e loro modifiche, regole ed elementi delle pulizie,
macchine vere, prodotti della produzione, gruppi chat, foto profilo, saldi ferie, iscrizioni alle notifiche.
Le pulizie da fare si ricreano da sole dalle regole quando qualcuno apre il turno.
"""

from django.db import migrations

# dai figli ai padri, così nessun collegamento blocca la cancellazione
DA_SVUOTARE = [
    'AllegatoPulizia', 'AvvisoPulizia', 'Straordinaria', 'Pulizia', 'PuliziaGenerale', 'ArchivioPulizie',
    'Annuncio', 'Notifica', 'LetturaChat', 'MessaggioChat',
    'Disponibilita', 'TurnoExtra', 'CambioTurno', 'RichiestaFerie', 'AvvisoAssenza',
    'InvitoRiunione', 'Riunione', 'PresaVisione', 'Documento', 'Scadenza',
    'RispostaComunicazione', 'FotoComunicazione', 'Comunicazione',
    'FermoImpianto', 'RicambioUsato', 'OrdineRicambio', 'EventoIntervento', 'FotoIntervento', 'Intervento',
    'RigaProduzione', 'ProduzioneTurno', 'AnalisiProdotto',
    'ConversazioneAssistente', 'BloccoAccesso',
    'ManutenzioneProgrammata', 'Ricambio',
]


def _togli_file(qs):
    campi = [f.name for f in qs.model._meta.get_fields() if getattr(f, 'upload_to', None) is not None]
    if not campi:
        return
    for oggetto in qs.iterator():
        for nome in campi:
            campo = getattr(oggetto, nome)
            if campo:
                try:
                    campo.storage.delete(campo.name)
                except Exception:
                    pass  # disco non raggiungibile da qui: il file resta, ma nessuno lo vede più


def azzera(apps, schema_editor):
    contati = {}
    MessaggioChat = apps.get_model('turni', 'MessaggioChat')
    MessaggioChat.objects.update(risposta_a=None)  # le risposte puntano ad altri messaggi
    for nome in DA_SVUOTARE:
        modello = apps.get_model('turni', nome)
        qs = modello.objects.all()
        _togli_file(qs)
        contati[nome] = qs.count()
        qs.delete()
    Macchina = apps.get_model('turni', 'Macchina')
    esempi = Macchina.objects.filter(esempio=True)
    _togli_file(esempi)
    contati['Macchina (esempi)'] = esempi.count()
    esempi.delete()
    apps.get_model('turni', 'StatoMessaggi').objects.update(bacheca_letta_il=None)
    apps.get_model('turni', 'Dipendente').objects.update(tentativi_falliti=0, bloccato_fino=None)
    righe = ', '.join(f'{n} {v}' for n, v in contati.items() if v)
    print(f'\n  Dati di prova cancellati: {righe or "nessuno"}.')


class Migration(migrations.Migration):
    dependencies = [('turni', '0084_aree_scarto_granella_sabbia_officina')]

    operations = [migrations.RunPython(azzera, migrations.RunPython.noop)]
