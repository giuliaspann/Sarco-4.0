"""Le pulizie del foglio "Regole Pulizie per Area e Ruolo" (file del responsabile turni, novembre 2026).

Si applicano una volta con una migrazione: dopo, l'ufficio le cambia dall'amministrazione.
Le funzioni ricevono le classi dei modelli, così le usa sia la migrazione sia un comando.

Come ho letto le colonne del foglio:
- "Modalità convalida": Solo Tasto -> SOLO_TASTO; Tasto + Foto Prima e Dopo -> PULIZIA_FOTO;
  Tasto + Foto Dopo -> FOTO_DOPO; Tasto + Foto Opzionale -> PULIZIA (o CONTROLLO per i controlli).
- "Chi convalida": con il Capo Turno nella catena ("CT > RP", "M > CT > RP", "RP > CT > RP") -> CT_RP:
  prima l'ok del Capo Turno, poi la convalida del responsabile piazzale (deciso con Giulia il 10/11/2026);
  "OdL > RP", "P > RP", "M > RP" -> chi esegue conferma e convalida il responsabile piazzale.
- "Quando" + "Durata": "Fine turno" con durata N minuti -> si fa dagli ultimi N minuti; il resto va nelle istruzioni.
- Le pulizie "Manuali" (notte dell'Impianto 1, straordinarie del piazzale) non hanno regole: le chiede il
  responsabile piazzale o impianto con "Richiedi".
"""

# nomi vecchi delle voci dell'app -> nome nel foglio (così lo storico resta attaccato alla voce)
RINOMINA = {
    'Linea incolore': 'Incolore',
    'Linea barrotti': 'Barrotti',
    'Mulino a barre e pressa': 'Mulino e pressa',
    'Controllo pala': 'Pala',
    'Piazzale': 'Piazzale + corridoio granella',
}

# voci che restano come sono (hanno funzioni loro)
INTOCCABILI = {'Pulizia generale Impianto 2'}


def r(postazione='', fascia='', ruolo='', giorno=None, a_rotazione=False):
    return {'postazione': postazione, 'fascia': fascia, 'ruolo': ruolo, 'giorno': giorno, 'a_rotazione': a_rotazione}


TRE = ('1T', '2T', 'N')

VOCI = [
    {'nome': 'Pozzetti', 'luogo': 'IMP1', 'modo': 'SOLO_TASTO', 'convalida': 'CT_RP', 'minuti': None,
     'istruzioni': 'Inizio turno · 40 minuti. Una persona al giorno, a turno tra gli operatori di linea.',
     'regole': [r('IMP1', '1T', 'OdL', a_rotazione=True)]},
    {'nome': 'Macchine ottiche', 'luogo': 'IMP1', 'modo': 'SOLO_TASTO', 'convalida': 'CT_RP', 'minuti': None,
     'istruzioni': 'A metà e a fine turno · 15 minuti. La fa il manutentore, la approva il Capo Turno, poi il responsabile piazzale.',
     'regole': [r('IMP1', f, 'Man') for f in TRE]},
    {'nome': 'Pavimentazione + altro', 'luogo': 'IMP1', 'modo': 'SOLO_TASTO', 'convalida': 'CT_RP', 'minuti': 30,
     'istruzioni': 'Fine turno · 30 minuti. La fa chi non fa le macchine ottiche.',
     'regole': [r('IMP1', '1T', 'OdL'), r('IMP1', '2T', 'OdL')]},
    {'nome': 'Generiche Impianto 1 (notte)', 'luogo': 'IMP1', 'modo': 'PULIZIA_FOTO', 'convalida': 'CT_RP', 'minuti': 60,
     'istruzioni': 'Fine turno · 60 minuti. Le assegna il responsabile piazzale ai Capi Turno entro le 17:00; '
                   'il Capo Turno le affida a voce agli operatori.',
     'regole': []},
    {'nome': 'Controllo vagli zig-zag', 'luogo': 'IMP1', 'modo': 'CONTROLLO', 'convalida': 'CT_RP', 'minuti': 60,
     'promemoria': True,
     'istruzioni': 'Fine turno · 60 minuti. Lo fa il manutentore; il Capo Turno lo affida a voce a 2 operatori. Foto facoltativa.',
     'regole': [r('IMP1', '1T', giorno=2), r('IMP1', '2T', giorno=5)]},
    {'nome': 'Incolore', 'luogo': 'IMP2', 'modo': 'PULIZIA_FOTO', 'convalida': 'PIAZZALE', 'minuti': 60,
     'istruzioni': 'Fine turno · 60 minuti.',
     'regole': [r('IMP2', f) for f in TRE]},
    {'nome': 'Barrotti', 'luogo': 'IMP2', 'modo': 'FOTO_DOPO', 'convalida': 'PIAZZALE', 'minuti': 30,
     'istruzioni': 'Fine turno · 30 minuti.',
     'regole': [r('BARROTTI')]},
    {'nome': 'Mulino e pressa', 'luogo': 'SABBIA', 'modo': 'SOLO_TASTO', 'convalida': 'PIAZZALE', 'minuti': 30,
     'istruzioni': 'Fine turno, solo per il giornaliero.',
     'regole': [r('SABBIA', 'G'), r('MULINO', 'G')]},
    {'nome': 'Generiche Sabbia Superbi', 'luogo': 'SABBIA', 'modo': 'PULIZIA_FOTO', 'convalida': 'CT_RP', 'minuti': 30,
     'istruzioni': 'Fine turno · 30 minuti.',
     'regole': [r('SUPERBI', f) for f in TRE]},
    {'nome': 'Generiche Rotovaglio', 'luogo': 'PIAZZALE', 'modo': 'PULIZIA_FOTO', 'convalida': 'PIAZZALE', 'minuti': 30,
     'istruzioni': 'Fine turno · 30 minuti.',
     'regole': [r('ROTOVAGLIO')]},
    {'nome': 'Pala', 'luogo': 'MEZZI', 'tipo': 'MEZZO', 'modo': 'PULIZIA_FOTO', 'convalida': 'PIAZZALE', 'minuti': 30,
     'istruzioni': 'Fine turno: controllo e pulizia · 30 minuti.',
     'regole': [r('IMP1', ruolo='Pal'), r('PALISTA')]},
    {'nome': 'Piazzale + corridoio granella', 'luogo': 'PIAZZALE', 'modo': 'SOLO_TASTO', 'convalida': 'PIAZZALE', 'minuti': None,
     'istruzioni': 'Inizio turno · 30 minuti.',
     'regole': [r('IMP1', '1T', 'Pal'), r('PALISTA', '1T')]},
    {'nome': 'Generiche Metalli', 'luogo': 'METALLI', 'modo': 'PULIZIA_FOTO', 'convalida': 'PIAZZALE', 'minuti': 30,
     'istruzioni': 'Fine turno · 30 minuti.',
     'regole': [r('METALLI')]},
    {'nome': 'Generiche Manutenzione', 'luogo': '', 'modo': 'SOLO_TASTO', 'convalida': 'PIAZZALE', 'minuti': 30,
     'istruzioni': 'Fine turno · 30 minuti (compare 30 minuti prima della fine del turno).',
     'regole': [r('MANUT'), r('IMP1', ruolo='Man')]},
    {'nome': 'Pulizie straordinarie piazzale', 'luogo': 'PIAZZALE', 'modo': 'PULIZIA_FOTO', 'convalida': 'CT_RP', 'minuti': None,
     'istruzioni': 'Durante il turno. Le assegnano il responsabile impianto o il responsabile piazzale ai Capi Turno.',
     'regole': []},
    {'nome': 'Carrelli elevatori', 'luogo': 'MEZZI', 'tipo': 'MEZZO', 'modo': 'FOTO_DOPO', 'convalida': 'PIAZZALE', 'minuti': None,
     'istruzioni': 'Ingrassaggio e pulizia, sabato 2° turno.',
     'regole': [r('MANUT', '2T', giorno=5, a_rotazione=True), r('IMP1', '2T', 'Man', giorno=5, a_rotazione=True)]},
]


def applica(Elemento, Regola):
    """Crea o aggiorna le voci del foglio, ne riscrive le regole e spegne le voci vecchie che il foglio non ha."""
    for vecchio, nuovo in RINOMINA.items():
        e = Elemento.objects.filter(nome=vecchio).first()
        if e and not Elemento.objects.filter(nome=nuovo).exists():
            e.nome = nuovo
            e.save(update_fields=['nome'])
    tenute = set(INTOCCABILI)
    for ordine, v in enumerate(VOCI, start=1):
        e, _ = Elemento.objects.get_or_create(nome=v['nome'], defaults={'tipo': v.get('tipo', 'ZONA')})
        e.tipo = v.get('tipo', 'ZONA')
        e.luogo = v['luogo']
        e.modo = v['modo']
        e.convalida = v['convalida']
        e.minuti_prima_fine = v['minuti']
        e.istruzioni = v['istruzioni']
        e.promemoria = v.get('promemoria', False)
        e.ordine = ordine * 5
        e.attivo = True
        e.save()
        Regola.objects.filter(elemento=e).delete()
        for regola in v['regole']:
            Regola.objects.create(elemento=e, **regola)
        tenute.add(e.nome)
    Elemento.objects.exclude(nome__in=tenute).update(attivo=False)
