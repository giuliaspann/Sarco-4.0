"""Macchine, mezzi, ricambi e programmate d'esempio, per vedere la Manutenzione prima dell'elenco vero.

Tutto è segnato `esempio=True`: dalla pagina Macchine il responsabile li toglie con un tasto.
"""

from datetime import timedelta

# codice, nome, tipo, categoria, luogo, marca, modello
MACCHINE = [
    ('IMP1-TRM', 'Tramoggia di carico', 'IMPIANTO', 'Tramoggia', 'IMP1', '', ''),
    ('IMP1-TRI', 'Trituratore primario', 'IMPIANTO', 'Trituratore', 'IMP1', 'Doppstadt', 'DW 3060'),
    ('IMP1-NAS1', 'Nastro trasportatore principale', 'IMPIANTO', 'Nastro', 'IMP1', '', '800 mm'),
    ('IMP1-VAG', 'Vaglio rotante', 'IMPIANTO', 'Vaglio', 'IMP1', 'Terex', 'Trommel 6'),
    ('IMP1-DEF', 'Separatore magnetico', 'IMPIANTO', 'Separatore', 'IMP1', 'Sesotec', ''),
    ('IMP2-NAS1', 'Nastro di selezione', 'IMPIANTO', 'Nastro', 'IMP2', '', '1000 mm'),
    ('IMP2-VAG', 'Vaglio a dischi', 'IMPIANTO', 'Vaglio', 'IMP2', '', ''),
    ('IMP2-PRE', 'Pressa imballatrice', 'IMPIANTO', 'Pressa', 'IMP2', 'Macpresse', 'MAC 108'),
    ('IMP2-CMP', 'Compressore aria', 'IMPIANTO', 'Compressore', 'IMP2', 'Atlas Copco', 'GA 30'),
    ('PZ-PALA1', 'Pala gommata 1', 'MEZZO', 'Pala gommata', 'PIAZZALE', 'Volvo', 'L90H'),
    ('PZ-PALA2', 'Pala gommata 2', 'MEZZO', 'Pala gommata', 'PIAZZALE', 'Caterpillar', '950M'),
    ('PZ-ESC1', 'Escavatore con polipo', 'MEZZO', 'Escavatore', 'PIAZZALE', 'Fuchs', 'MHL 340'),
    ('PZ-MUL1', 'Muletto 1', 'MEZZO', 'Muletto', 'PIAZZALE', 'Linde', 'H30D'),
    ('PZ-PESA', 'Pesa a ponte', 'IMPIANTO', 'Pesa', 'PIAZZALE', '', '60 t'),
    ('MET-CES', 'Cesoia rottami', 'IMPIANTO', 'Cesoia', 'METALLI', '', ''),
    ('MET-ECS', 'Separatore a correnti indotte', 'IMPIANTO', 'Separatore', 'METALLI', 'Steinert', ''),
    ('MET-MUL', 'Muletto rottami', 'MEZZO', 'Muletto', 'METALLI', 'Still', 'RX70'),
    ('SAB-IDR', 'Idrociclone lavaggio sabbia', 'IMPIANTO', 'Lavaggio', 'SABBIA', 'CDE', ''),
    ('SAB-VAG', 'Vaglio vibrante sabbia', 'IMPIANTO', 'Vaglio', 'SABBIA', '', ''),
    ('SAB-NAS', 'Nastro stoccaggio sabbia', 'IMPIANTO', 'Nastro', 'SABBIA', '', '650 mm'),
]

# nome, codice, scorta, minima, unità, dove, fornitore, macchine
RICAMBI = [
    ('Filtro olio motore', 'VOE 21707134', 2, 2, 'pz', 'Scaffale A1', 'Volvo CE', ['PZ-PALA1']),
    ('Filtro aria motore', 'CAT 1318822', 1, 1, 'pz', 'Scaffale A1', 'Caterpillar', ['PZ-PALA2']),
    ('Olio idraulico ISO 46', '', 40, 50, 'l', 'Magazzino oli', 'Q8', ['PZ-PALA1', 'PZ-PALA2', 'PZ-ESC1', 'IMP2-PRE']),
    ('Cuscinetto SKF 6310', '6310-2RS', 6, 4, 'pz', 'Scaffale B2', 'SKF', ['IMP1-NAS1', 'IMP2-NAS1', 'SAB-NAS']),
    ('Rullo portante nastro 800', '', 3, 4, 'pz', 'Piazzale ricambi', '', ['IMP1-NAS1']),
    ('Raschiatore nastro', '', 2, 1, 'pz', 'Scaffale B3', '', ['IMP1-NAS1', 'IMP2-NAS1', 'SAB-NAS']),
    ('Denti trituratore', '', 12, 8, 'pz', 'Scaffale C1', 'Doppstadt', ['IMP1-TRI']),
    ('Cinghia trapezoidale B68', 'B68', 4, 2, 'pz', 'Scaffale B1', '', ['IMP1-VAG', 'SAB-VAG']),
    ('Filo legatura balle', '', 3, 2, 'rotoli', 'Vicino pressa', '', ['IMP2-PRE']),
    ('Pneumatico 20.5R25', '', 0, 1, 'pz', '', 'Michelin', ['PZ-PALA1', 'PZ-PALA2']),
]

# codice macchina, attività, ogni giorni, giorni dall'ultima, istruzioni
PROGRAMMATE = [
    ('PZ-PALA1', 'Ingrassaggio perni e snodi', 7, 8, 'Perni benna\nSnodo centrale\nCilindri di sollevamento'),
    ('PZ-PALA2', 'Ingrassaggio perni e snodi', 7, 3, 'Perni benna\nSnodo centrale\nCilindri di sollevamento'),
    ('PZ-PALA1', 'Tagliando motore (500 ore)', 90, 40, 'Cambio olio motore\nFiltro olio\nFiltro gasolio\nControllo cinghie'),
    ('IMP1-NAS1', 'Controllo tensione nastro e rulli', 14, 15, 'Tensione tappeto\nRulli portanti che non girano\nRaschiatori'),
    ('IMP2-CMP', 'Scarico condensa e pulizia filtro', 30, 25, 'Scarico condensa\nPulizia filtro aspirazione\nLivello olio'),
    ('PZ-MUL1', 'Controllo olio, freni e catene', 7, 2, 'Livello olio motore\nFreni\nCatene montante\nForche'),
]


def carica(apps):
    from django.utils import timezone

    Macchina = apps.get_model('turni', 'Macchina')
    Ricambio = apps.get_model('turni', 'Ricambio')
    Programmata = apps.get_model('turni', 'ManutenzioneProgrammata')
    Intervento = apps.get_model('turni', 'Intervento')
    Evento = apps.get_model('turni', 'EventoIntervento')
    Dipendente = apps.get_model('turni', 'Dipendente')

    if Macchina.objects.exists():
        return
    oggi = timezone.localdate()
    adesso = timezone.now()
    m = {}
    for codice, nome, tipo, categoria, luogo, marca, modello in MACCHINE:
        m[codice] = Macchina.objects.create(
            codice=codice, nome=nome, tipo=tipo, categoria=categoria, luogo=luogo,
            marca=marca, modello=modello, esempio=True,
        )
    for nome, codice, scorta, minima, unita, dove, fornitore, macchine in RICAMBI:
        r = Ricambio.objects.create(nome=nome, codice=codice, scorta=scorta, scorta_minima=minima, unita=unita,
                                    ubicazione=dove, fornitore=fornitore, esempio=True)
        r.macchine.set([m[c] for c in macchine])
    for codice, attivita, ogni, fa, istruzioni in PROGRAMMATE:
        Programmata.objects.create(macchina=m[codice], attivita=attivita, ogni_giorni=ogni,
                                   ultima=oggi - timedelta(days=fa), istruzioni=istruzioni)

    manutentore = Dipendente.objects.filter(mansione__contains='MANUTENTORE', attivo=True).first()
    i = Intervento.objects.create(
        macchina=m['PZ-PALA2'], descrizione='Perde olio idraulico dal cilindro del braccio, sotto la pala c\'è una macchia.',
        macchina_ferma=True, priorita=4, segnalata_il=adesso - timedelta(hours=3),
    )
    Evento.objects.create(intervento=i, testo='Guasto segnalato (esempio)', creato_il=i.segnalata_il)
    i = Intervento.objects.create(
        macchina=m['IMP1-NAS1'], descrizione='Il nastro slitta in partenza e fa rumore sul rullo di coda.',
        priorita=3, stato='ASSEGNATA', assegnata_a=manutentore, segnalata_il=adesso - timedelta(hours=20),
        approvata_il=adesso - timedelta(hours=19),
    )
    Evento.objects.create(intervento=i, testo='Guasto segnalato (esempio)', creato_il=i.segnalata_il)
    Evento.objects.create(intervento=i, testo=f'Approvato e assegnato a {manutentore.nome.title() if manutentore else "manutentore"}',
                          creato_il=i.approvata_il)
    i = Intervento.objects.create(
        macchina=m['IMP2-PRE'], descrizione='Il filo di legatura si inceppa e le balle escono aperte.',
        priorita=2, stato='COMPLETATA', assegnata_a=manutentore, segnalata_il=adesso - timedelta(days=3, hours=5),
        approvata_il=adesso - timedelta(days=3, hours=4), iniziata_il=adesso - timedelta(days=3, hours=3),
        completata_il=adesso - timedelta(days=3, hours=1), ore_lavoro=2,
        lavoro_svolto='Pulito il guidafilo e sostituito il rotolo di filo. Prova con 5 balle: ok.',
    )
    for testo, ore in (('Guasto segnalato (esempio)', 5), ('Approvato e assegnato', 4), ('Lavoro iniziato', 3), ('Riparato', 1)):
        Evento.objects.create(intervento=i, testo=testo, creato_il=adesso - timedelta(days=3, hours=ore))


def togli():
    """Elimina gli esempi (con i loro interventi, ordini e programmate). Restituisce quante macchine."""
    from .models import Intervento, Macchina, OrdineRicambio, Ricambio

    esempi = Macchina.objects.filter(esempio=True)
    OrdineRicambio.objects.filter(macchina__in=esempi).delete()
    Intervento.objects.filter(macchina__in=esempi).delete()
    Ricambio.objects.filter(esempio=True).delete()
    n = esempi.count()
    esempi.delete()
    return n
