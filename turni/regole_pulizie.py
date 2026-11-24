"""Le pulizie del file «Regole Pulizie - unico.xlsx» (Giulia, 21/11/2026): da ora è questo file a dettare le regole
della funzione Pulizia. Ogni voce qui sotto è una riga del primo foglio «Regole Pulizie».

Come leggo le colonne del file:
- «Orario» + «Durata (min)»: Fine turno → si conferma solo negli ultimi N minuti (minuti_prima_fine);
  Metà turno → da metà turno in poi (da_meta); Inizio turno → in qualsiasi momento del turno.
- «Foto»: No → SOLO_TASTO (o CONTROLLO per i controlli); Prima e dopo → PULIZIA_FOTO; Dopo → FOTO_DOPO.
  Si possono sempre aggiungere più foto, video e la nota (nota di Giulia nel foglio Regole generali).
- «Chi Convalida»: CT > RP, RP > CT > RP, M > CT > RP → CT_RP (prima il Capo Turno, poi il responsabile piazzale);
  OdL > RP, P > RP, M > RP → PIAZZALE (direttamente il responsabile piazzale).
- «Avviso - minuti» + «Avviso - momento» + «Avviso - a chi»: avviso, avviso_minuti, avviso_a.
  Capo Turno → CT; Capo Turno e Manutentore → CT_MAN; OdL, Palista, Manutentore (chi fa la pulizia) → ADDETTI.
- «Turni: Ultimo turno della settimana» → regola con ultimo_settimana.

La vecchia lista (regole_foglio.py) resta com'era perché la usano le migrazioni vecchie.
"""

from .regole_foglio import aggiorna_avviso

# nomi di prima → nomi del file (così lo storico resta attaccato alla voce)
RINOMINA = {
    'Macchine ottiche': 'Macchine ottiche - metà turno',
    'Generiche Impianto 1 (notte)': 'Generiche Notturne',
    'Incolore': 'Linea Incolore',
    'Barrotti': 'Linea Scarto',
    'Linea Barrotti': 'Linea Scarto',  # area rinominata il 23/11/2026
    'Generiche Metalli': 'Area Metalli',
    'Generiche Rotovaglio': 'Area Rotovaglio',
    'Rotovaglio': 'Area Rotovaglio',  # nome del file del 22/11/2026
    'Piazzale + corridoio granella': 'Piazzale',
    'Generiche Sabbia Superbi': 'Generiche Sabbia',
    'Generiche Superbi': 'Generiche Sabbia',  # area rinominata il 23/11/2026
    'Carrelli elevatori': 'Ingrassaggio e Pulizia Carrelli Elevatori',
    'Pala': 'Pulizia Settimanale Pala',
}

NOTTURNE = 'Generiche Notturne'

# colonna «Durata (min)» del file, voce per voce (Giulia, 24/11/2026)
DURATE = {
          'Pozzetti': 40,
          'Macchine ottiche - metà turno': 15,
          'Macchine ottiche - fine turno': 15,
          'Pavimentazione + altro': 30,
          'Controllo vagli zig-zag': 60,
          'Generiche Notturne': 60,
          'Linea Incolore': 75,
          'Linea Scarto': 30,
          'Area Metalli': 30,
          'Pulizia Settimanale Area Metalli': 40,
          'Pulizia Settimanale Pala': 40,
          'Ingrassaggio e Pulizia Carrelli Elevatori': 90,
          'Area Rotovaglio': 30,
          'Piazzale': 30,
          'Mulino e pressa': 30,
          'Generiche Sabbia': 30}


def r(postazione='', fascia='', ruolo='', giorno=None, a_rotazione=False, scelta='', ultimo=False):
    return {'postazione': postazione, 'fascia': fascia, 'ruolo': ruolo, 'giorno': giorno, 'a_rotazione': a_rotazione,
            'scelta': scelta, 'ultimo_settimana': ultimo}


TRE = ('1T', '2T', 'N')
PRIMA, INIZIO, DMETA = 'PRIMA', 'INIZIO', 'DMETA'


def avv(momento, minuti, a):
    return {'avviso': momento, 'avviso_minuti': minuti, 'avviso_a': a}


VOCI = [
    {'nome': 'Pozzetti', 'luogo': 'IMP1', 'modo': 'SOLO_TASTO', 'convalida': 'CT_RP', 'minuti': None, 'tasto': 'Conferma pulizia',
     'istruzioni': 'Inizio turno · 40 minuti. Gli OdL del 1° turno, a rotazione (uno al giorno); conferma il Capo Turno, '
                   'che con «Fatta da» indica il collega che li ha puliti.',
     'avviso': avv(INIZIO, 60, 'CT'),
     'regole': [r('IMP1', '1T', 'OdL', a_rotazione=True)]},
    {'nome': 'Macchine ottiche - metà turno', 'luogo': 'IMP1', 'modo': 'SOLO_TASTO', 'convalida': 'CT_RP', 'minuti': None,
     'da_meta': True, 'tasto': '',
     'istruzioni': 'Metà turno · 15 minuti. 2 OdL competenti per le macchine ottiche (prima chi ha 1, poi chi ha 2); '
                   'il Capo Turno tocca «Pulizia ottiche iniziata» e poi «Pulizia ottiche conclusa».',
     'avviso': dict(avv(DMETA, 15, 'CT'), con_avvio=True),
     'regole': [r('IMP1', f, 'OdL', scelta='MO') for f in TRE]},
    {'nome': 'Macchine ottiche - fine turno', 'luogo': 'IMP1', 'modo': 'SOLO_TASTO', 'convalida': 'CT_RP', 'minuti': 15, 'tasto': '',
     'istruzioni': 'Fine turno · 15 minuti. 2 OdL competenti per le macchine ottiche (prima chi ha 1, poi chi ha 2); '
                   'il Capo Turno tocca «Pulizia ottiche iniziata» e poi «Pulizia ottiche conclusa».',
     'avviso': dict(avv(PRIMA, 15, 'CT'), con_avvio=True),
     'regole': [r('IMP1', f, 'OdL', scelta='MO') for f in TRE]},
    {'nome': 'Pavimentazione + altro', 'luogo': 'IMP1', 'modo': 'SOLO_TASTO', 'convalida': 'CT_RP', 'minuti': 30, 'tasto': 'Conferma pulizia',
     'istruzioni': 'Fine turno · 30 minuti. Gli OdL di Impianto 1 che quel giorno non fanno le macchine ottiche; conferma il Capo Turno.',
     'avviso': avv(PRIMA, 15, 'CT'),
     'regole': [r('IMP1', '1T', 'OdL', scelta='NO_MO'), r('IMP1', '2T', 'OdL', scelta='NO_MO')]},
    {'nome': 'Controllo vagli zig-zag', 'luogo': 'IMP1', 'modo': 'CONTROLLO', 'convalida': 'CT_RP', 'minuti': 60, 'promemoria': True,
     'tasto': 'Controllo fatto',
     'istruzioni': 'Fine turno · 60 minuti. Il Manutentore di turno (se manca, chi indica il Capo Turno): «Controllo fatto» '
                   'oppure «Segnala un problema». Conferma il Manutentore, verifica il Capo Turno, convalida il responsabile piazzale.',
     'avviso': avv(PRIMA, 45, 'CT_MAN'),
     'regole': [r('IMP1', '1T', giorno=2), r('IMP1', '2T', giorno=5)]},
    {'nome': NOTTURNE, 'luogo': 'IMP1', 'modo': 'PULIZIA_FOTO', 'convalida': 'CT_RP', 'minuti': 60, 'tasto': 'Conferma pulizia',
     'istruzioni': 'Fine turno · 60 minuti. Le assegna il responsabile piazzale ai Capi Turno del Notturno entro le 17:00 '
                   '(se è assente, le registra il Capo Turno); il Capo Turno le affida a voce agli OdL e le conferma.',
     'avviso': avv(PRIMA, 30, 'CT'),
     'regole': []},
    {'nome': 'Linea Incolore', 'luogo': 'IMP2', 'modo': 'PULIZIA_FOTO', 'convalida': 'PIAZZALE', 'minuti': 75, 'tasto': 'Conferma pulizia',
     'istruzioni': "Fine turno · 75 minuti. L'OdL che lavora a Impianto 2 - Incolore.",
     'avviso': avv(PRIMA, 75, 'ADDETTI'),
     'regole': [r('IMP2', f) for f in TRE]},
    {'nome': 'Linea Scarto', 'luogo': 'IMP2', 'modo': 'FOTO_DOPO', 'convalida': 'PIAZZALE', 'minuti': 30, 'tasto': 'Conferma pulizia',
     'istruzioni': "Fine turno · 30 minuti. L'OdL che lavora a Impianto 2 - Scarto.",
     'avviso': avv(PRIMA, 15, 'ADDETTI'),
     'regole': [r('BARROTTI')]},
    {'nome': 'Area Metalli', 'luogo': 'METALLI', 'modo': 'PULIZIA_FOTO', 'convalida': 'PIAZZALE', 'minuti': 30, 'tasto': 'Controllo fatto',
     'istruzioni': 'Fine turno · 30 minuti, ogni turno Giornaliero. Il Palista che lavora alla postazione Metalli.',
     'avviso': avv(PRIMA, 15, 'ADDETTI'),
     'regole': [r('METALLI', 'G')]},
    {'nome': 'Pulizia Settimanale Area Metalli', 'luogo': 'METALLI', 'modo': 'PULIZIA_FOTO', 'convalida': 'PIAZZALE', 'minuti': 40,
     'tasto': 'Conferma pulizia',
     'istruzioni': "Una volta a settimana, nell'ultimo turno della settimana ai Metalli · fine turno, 40 minuti.",
     'avviso': avv(PRIMA, 20, 'ADDETTI'),
     'regole': [r('METALLI', ultimo=True)]},
    {'nome': 'Pulizia Settimanale Pala', 'luogo': 'MEZZI', 'tipo': 'MEZZO', 'modo': 'PULIZIA_FOTO', 'convalida': 'PIAZZALE', 'minuti': 40,
     'tasto': 'Conferma pulizia',
     'istruzioni': "Una volta a settimana, nell'ultimo turno della settimana del Palista · fine turno, 40 minuti.",
     'avviso': avv(PRIMA, 20, 'ADDETTI'),
     'regole': [r('PALISTA', ultimo=True), r('IMP1', ruolo='Pal', ultimo=True)]},
    {'nome': 'Ingrassaggio e Pulizia Carrelli Elevatori', 'luogo': 'MEZZI', 'tipo': 'MEZZO', 'modo': 'PULIZIA_FOTO', 'convalida': 'PIAZZALE',
     'minuti': 90, 'tasto': 'Conferma ingrassaggio e pulizia',
     'istruzioni': "Una volta a settimana, nell'ultimo turno della settimana del Manutentore · fine turno, 90 minuti.",
     'avviso': avv(PRIMA, 60, 'ADDETTI'),
     'regole': [r('MANUT', a_rotazione=True, ultimo=True), r(ruolo='Man', a_rotazione=True, ultimo=True)]},
    {'nome': 'Area Rotovaglio', 'luogo': 'ROTOVAGLIO', 'modo': 'PULIZIA_FOTO', 'convalida': 'PIAZZALE', 'minuti': 30, 'tasto': 'Conferma pulizia',
     'istruzioni': 'Fine turno · 30 minuti. Il Palista che lavora al Rotovaglio.',
     'avviso': avv(PRIMA, 15, 'ADDETTI'),
     'regole': [r('ROTOVAGLIO')]},
    {'nome': 'Piazzale', 'luogo': 'PIAZZALE', 'modo': 'SOLO_TASTO', 'convalida': 'PIAZZALE', 'minuti': None, 'tasto': 'Piazzale pulito',
     'istruzioni': 'Inizio turno · 30 minuti. Il Palista di Impianto 1, 1° turno.',
     'avviso': avv(INIZIO, 30, 'ADDETTI'),
     'regole': [r('IMP1', '1T', 'Pal'), r('PALISTA', '1T')]},
    {'nome': 'Mulino e pressa', 'luogo': 'GRANELLA', 'modo': 'SOLO_TASTO', 'convalida': 'PIAZZALE', 'minuti': 30, 'tasto': 'Controllo fatto',
     'istruzioni': 'Fine turno · 30 minuti, solo turno Giornaliero. Chi lavora a Granella.',
     'avviso': avv(PRIMA, 15, 'ADDETTI'),
     'regole': [r('SABBIA', 'G'), r('MULINO', 'G')]},
    {'nome': 'Generiche Sabbia', 'luogo': 'SABBIA', 'modo': 'PULIZIA_FOTO', 'convalida': 'PIAZZALE', 'minuti': 30, 'tasto': 'Conferma pulizia',
     'istruzioni': 'Fine turno · 30 minuti. Chi lavora a Sabbia.',
     'avviso': avv(PRIMA, 15, 'ADDETTI'),
     'regole': [r('SUPERBI')]},
]


def applica(Elemento, Regola):
    """Crea o aggiorna le voci del file, ne riscrive le regole e spegne tutte le altre (anche la pulizia generale Impianto 2)."""
    for vecchio, nuovo in RINOMINA.items():
        e = Elemento.objects.filter(nome=vecchio).first()
        if e and not Elemento.objects.filter(nome=nuovo).exists():
            e.nome = nuovo
            e.save(update_fields=['nome'])
    tenute = set()
    campi_e = {f.name for f in Elemento._meta.get_fields()}
    campi_r = {f.name for f in Regola._meta.get_fields()}
    for ordine, v in enumerate(VOCI, start=1):
        e, _ = Elemento.objects.get_or_create(nome=v['nome'], defaults={'tipo': v.get('tipo', 'ZONA')})
        e.tipo = v.get('tipo', 'ZONA')
        e.luogo = v['luogo']
        e.modo = v['modo']
        e.convalida = v['convalida']
        e.minuti_prima_fine = v['minuti']
        if 'durata' in campi_e:
            e.durata = DURATE.get(v['nome'])
        e.istruzioni = v['istruzioni']
        e.promemoria = v.get('promemoria', False)
        e.tasto = v.get('tasto', '')
        if 'da_meta' in campi_e:
            e.da_meta = v.get('da_meta', False)
        aggiorna_avviso(e, v.get('avviso'))
        e.ordine = ordine * 5
        e.attivo = True
        e.save()
        Regola.objects.filter(elemento=e).delete()
        for regola in v['regole']:
            Regola.objects.create(elemento=e, **{k: x for k, x in regola.items() if k in campi_r})
        tenute.add(e.nome)
    # si spengono solo le voci della lista di prima che il file non ha più (Pala giornaliera, Generiche Manutenzione,
    # Pulizie straordinarie piazzale, Pulizia generale Impianto 2): le voci nate da una macchina restano come sono
    from . import regole_foglio as vecchie

    di_prima = {v['nome'] for v in vecchie.VOCI} | set(vecchie.INTOCCABILI) | set(vecchie.RINOMINA) | set(RINOMINA)
    Elemento.objects.filter(nome__in=di_prima - tenute).update(attivo=False)
