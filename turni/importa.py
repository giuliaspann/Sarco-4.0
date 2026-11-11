"""Lettura del file turni settimanale (quello condiviso su WhatsApp).

Il file contiene un foglio per settimana ("Sett.1" ... "Sett.53") numerato come la
settimana ISO: "Sett.42" del 2026 va dal 12/10 al 18/10. In ogni foglio la tabella
inizia dalla riga con "DIPENDENTI" in colonna B, con i giorni da lunedì a domenica
nelle colonne C-I. A destra (K-M) ci sono le note su ferie e richieste, in fondo
il riquadro "APPRENDISTI E TUTOR".
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

import openpyxl

from .models import Fascia, Postazione

POSTAZIONI = [
    (r'IMP\.?\s*1', Postazione.IMP1),
    (r'IMP\.?\s*2', Postazione.IMP2),
    (r'ANALISI', Postazione.ANALISI),
    (r'SUPERBI', Postazione.SUPERBI),
    (r'MULINO', Postazione.MULINO),
    (r'BARROTTI', Postazione.BARROTTI),
    (r'PALISTA', Postazione.PALISTA),
    (r'METALL', Postazione.METALLI),
    (r'SABBIA', Postazione.SABBIA),
    (r'PIAZZALE', Postazione.PIAZZALE),
    (r'AUTIST', Postazione.AUTISTA),
    (r'MANUT', Postazione.MANUT),
    (r'UFFICIO', Postazione.UFFICIO),
]

ASSENZE = {
    'RIP': Fascia.RIPOSO,
    'RIPOSO': Fascia.RIPOSO,
    'FERIE': Fascia.FERIE,
    'FESTA': Fascia.FESTA,
    'C.P.': Fascia.PERMESSO,
    'NOTTURNO': Fascia.NOTTE,
    'CP': Fascia.PERMESSO,
}


@dataclass
class CodiceTurno:
    codice: str
    fascia: str
    postazione: str = ''
    capoturno: bool = False
    ruolo: str = ''  # solo dal "Layout Turni": CT, OdL, Pal, Man, Aut…
    posto: str = ''  # solo dal "Layout Turni": "Impianto 1 · Operatore di Linea"
    incarichi: str = ''  # solo dal "Layout Turni": "IMP1/CT IMP1/Pal"
    sigla: str = ''  # solo dal "Layout Turni", come nella "Vista Dipendenti": "1T | Imp 1 | CT"


def interpreta_codice(testo):
    """'1T- Imp. 1 ' -> 1° turno Impianto 1; 'CAPO T. Imp. 1 N' -> capoturno notte Imp. 1; ..."""
    codice = ' '.join(str(testo or '').split())
    t = codice.upper()
    if not t:
        return CodiceTurno('', Fascia.RIPOSO)
    if t in ASSENZE:
        return CodiceTurno(codice, ASSENZE[t])

    capoturno = bool(re.match(r'CAPO\s*T', t))
    resto = re.sub(r'^CAPO\s*T\.?', '', t).strip(' -/')

    postazione = ''
    for modello, valore in POSTAZIONI:
        if re.search(modello, resto):
            postazione = valore
            resto = re.sub(modello, ' ', resto)
            break

    # quello che resta indica la fascia: 1T, 2T, N, G
    token = set(re.split(r'[\s\-/]+', resto)) - {''}
    if '1T' in token:
        fascia = Fascia.MATTINA
    elif '2T' in token:
        fascia = Fascia.POMERIGGIO
    elif 'N' in token:
        fascia = Fascia.NOTTE
    elif 'G' in token:
        fascia = Fascia.GIORNALIERO
    else:
        fascia = Fascia.ALTRO  # es. "CAPO T. - Imp. 1": la fascia non è scritta
    return CodiceTurno(codice, fascia, postazione, capoturno)


@dataclass
class RigaDipendente:
    nome: str
    turni: list  # 7 CodiceTurno, da lunedì a domenica


@dataclass
class SettimanaLetta:
    lunedi: date
    foglio: str
    righe: list = field(default_factory=list)
    note: list = field(default_factory=list)  # (riferimento, dipendente, testo)
    tutor: dict = field(default_factory=dict)  # apprendista -> tutor
    avvisi: list = field(default_factory=list)
    # solo dal "Layout Turni": le righe come nel foglio, per l'anteprima "Per Area"
    # [{'area': 'Imp 1', 'turno': '1T', 'ruolo': 'CT', 'fascia': '1T', 'nomi': [7 nomi o '-']}, …]
    layout: list = field(default_factory=list)


def lunedi_da_nome_file(nome):
    m = re.search(r'(\d{1,2})[-.](\d{1,2})[-.](\d{4})', nome or '')
    if not m:
        return None
    g, me, a = map(int, m.groups())
    d = date(a, me, g)
    return d - timedelta(days=d.weekday())


def pulisci(v):
    return ' '.join(str(v).split()) if v is not None else ''


def leggi_file(file, lunedi):
    wb = openpyxl.load_workbook(file, data_only=True)
    if FOGLIO_LAYOUT in wb.sheetnames:
        return leggi_layout(wb, lunedi)
    anno, settimana, _ = lunedi.isocalendar()
    nome_foglio = f'Sett.{settimana}'
    if nome_foglio in wb.sheetnames:
        ws = wb[nome_foglio]
        avvisi = []
    else:
        ws = wb.worksheets[-1]
        avvisi = [f'Foglio "{nome_foglio}" non trovato: uso l\'ultimo foglio "{ws.title}".']

    letta = SettimanaLetta(lunedi=lunedi, foglio=ws.title, avvisi=avvisi)

    intestazione = None
    for r in range(1, 15):
        if pulisci(ws.cell(r, 2).value).upper() == 'DIPENDENTI':
            intestazione = r
            break
    if intestazione is None:
        raise ValueError(f'Nel foglio "{ws.title}" non trovo la riga "DIPENDENTI" in colonna B.')

    r = intestazione + 1
    while True:
        nome = pulisci(ws.cell(r, 2).value)
        if not nome:
            break
        turni = [interpreta_codice(ws.cell(r, c).value) for c in range(3, 10)]
        letta.righe.append(RigaDipendente(nome.upper(), turni))
        r += 1

    # note a destra (K = settimana n., L = dipendente, M = testo), anche sulla riga d'intestazione
    for r in range(intestazione, ws.max_row + 1):
        rif, dip, testo = (pulisci(ws.cell(r, c).value) for c in (11, 12, 13))
        if dip.upper() == 'DIPENDENTI' or testo.upper() == 'RICHIESTA':
            continue
        if testo or dip:
            letta.note.append((rif, dip, testo))

    # riquadro apprendisti: "NOME (TUTOR1 E TUTOR2)" anche spezzato su due celle
    for r in range(1, ws.max_row + 1):
        for c in range(1, 17):
            if 'APPRENDISTI' in pulisci(ws.cell(r, c).value).upper():
                rr = r + 1
                while True:
                    riga = ' '.join(filter(None, (pulisci(ws.cell(rr, cc).value) for cc in range(c, c + 4))))
                    m = re.match(r'(.+?)\s*\((.+)\)', riga)
                    if not m:
                        break
                    letta.tutor[m.group(1).strip().upper()] = m.group(2).strip()
                    rr += 1
                break
    return letta


# ---------------------------------------------------------------- foglio "Layout Turni"
#
# Il file del responsabile turni ("Organizzazione Turni con Vista"): nel foglio "Layout Turni"
# ogni riga è un posto (Area, Turno, Ruolo, sigla del ruolo) con i nomi da lunedì a domenica;
# il turno è scritto solo sulla prima riga del blocco (celle unite). "Collegamento Nomi" dà il
# nome completo di chi nel layout è scritto per cognome. Gli altri fogli dell'Excel non servono.

FOGLIO_LAYOUT = 'Layout Turni'
FOGLIO_NOMI = 'Collegamento Nomi'
FOGLIO_VISTA = 'Vista Dipendenti'

FASCE_LAYOUT = {'1T': Fascia.MATTINA, '2T': Fascia.POMERIGGIO, 'N': Fascia.NOTTE, 'G': Fascia.GIORNALIERO}

# l'area decide la postazione (l'ordine conta: "Impianto 2 - Barrotti" prima di "Impianto 2")
AREE = [
    (r'BARR?OTTI', Postazione.BARROTTI),
    (r'IMPIANTO\s*2|INCOLORE', Postazione.IMP2),
    (r'IMPIANTO\s*1', Postazione.IMP1),
    (r'ROTOVAGLIO', Postazione.ROTOVAGLIO),
    (r'\bPALA\b', Postazione.PALISTA),
    (r'PIAZZALE', Postazione.PIAZZALE),
    (r'LABORATORIO|ANALISI', Postazione.ANALISI),
    (r'METALLI', Postazione.METALLI),
    (r'SUPERBI', Postazione.SUPERBI),
    (r'MULINO', Postazione.MULINO),
    (r'SABBIA', Postazione.SABBIA),
    (r'MANUTENZ', Postazione.MANUT),
    (r'TRASPORT|AUTIST', Postazione.AUTISTA),
    (r'UFFICIO', Postazione.UFFICIO),
    (r'MAGAZZINO', Postazione.MAGAZZINO),
]

def _postazione_area(area, sigla=''):
    """La postazione è l'area; palista e manutentore dell'Impianto 1 si distinguono dal ruolo (le regole pulizie lo usano)."""
    a = area.upper()
    for modello, valore in AREE:
        if re.search(modello, a):
            return valore
    return ''


def lunedi_dal_file(file):
    """Il lunedì scritto in "Vista Dipendenti" (cella C1), se il file è quello del Layout Turni."""
    from datetime import datetime

    v = None
    try:
        wb = openpyxl.load_workbook(file, data_only=True, read_only=True)
        if FOGLIO_VISTA in wb.sheetnames:
            v = wb[FOGLIO_VISTA]['C1'].value
    except Exception:
        v = None
    finally:
        if hasattr(file, 'seek'):
            file.seek(0)
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else None


def _collegamento_nomi(wb):
    nomi = {}
    if FOGLIO_NOMI not in wb.sheetnames:
        return nomi
    for breve, completo in wb[FOGLIO_NOMI].iter_rows(min_col=2, max_col=3, values_only=True):
        breve, completo = pulisci(breve), pulisci(completo)
        if breve and completo and breve.upper() != 'NOME NEL LAYOUT' and not completo.startswith('('):
            nomi[breve.upper()] = completo.upper()
    return nomi


def leggi_layout(wb, lunedi):
    ws = wb[FOGLIO_LAYOUT]
    letta = SettimanaLetta(lunedi=lunedi, foglio=ws.title)

    # intestazione: la riga con "Area" e "Turno"
    col, riga_int = {}, None
    for r in range(1, 15):
        testi = {}
        for c in range(1, 20):
            t = pulisci(ws.cell(r, c).value).upper()
            if t and t not in testi:
                testi[t] = c
        if 'AREA' in testi and 'TURNO' in testi:
            riga_int, col = r, testi
            break
    if riga_int is None:
        raise ValueError(f'Nel foglio "{ws.title}" non trovo l\'intestazione con "Area" e "Turno".')
    c_area, c_turno = col['AREA'], col['TURNO']
    c_ruolo, c_sigla = col.get('RUOLO'), col.get('RUOLO (ABBR.)')
    c_abbr = col.get('AREA (ABBR.)')
    # i giorni: "Lunedì" nella riga sopra l'intestazione (o nella stessa)
    primo = None
    for r in (riga_int - 1, riga_int):
        for c in range(1, 25):
            if r > 0 and pulisci(ws.cell(r, c).value).upper().startswith('LUN'):
                primo = c
                break
        if primo:
            break
    if primo is None:
        primo = max(col.values()) + 1

    nomi = _collegamento_nomi(wb)
    if not nomi:
        letta.avvisi.append('Manca il foglio "Collegamento Nomi": uso i nomi come sono scritti nel layout.')

    posti = {}  # (nome completo, giorno 0-6) -> assegnazioni
    ordine = list(dict.fromkeys(nomi.values()))  # tutti quelli dell'elenco, anche se a riposo
    area_prec, turno = None, ''
    sconosciuti, saltati = set(), set()
    for r in range(riga_int + 1, ws.max_row + 1):
        area = pulisci(ws.cell(r, c_area).value)
        if not area:
            continue
        t = pulisci(ws.cell(r, c_turno).value).upper()
        if t:
            turno = t
        elif area != area_prec:
            turno = ''
        area_prec = area
        ruolo = pulisci(ws.cell(r, c_ruolo).value) if c_ruolo else ''
        sigla = pulisci(ws.cell(r, c_sigla).value) if c_sigla else ''
        abbr = (pulisci(ws.cell(r, c_abbr).value) if c_abbr else '') or area
        fascia = FASCE_LAYOUT.get(turno, Fascia.ALTRO)
        letta.layout.append({'area': abbr, 'turno': turno, 'ruolo': sigla or ruolo, 'fascia': fascia,
                             'nomi': [pulisci(ws.cell(r, primo + i).value) or '-' for i in range(7)]})
        for i in range(7):
            v = pulisci(ws.cell(r, primo + i).value)
            if v in ('', '-', '–'):
                continue
            if len(v) <= 2 or v.startswith('('):  # segnaposto (X, Y…)
                saltati.add(v)
                continue
            completo = nomi.get(v.upper())
            if completo is None:
                completo = v.upper()
                sconosciuti.add(v)
            if completo not in ordine:
                ordine.append(completo)
            posti.setdefault((completo, i), []).append(
                {'fascia': fascia, 'turno': turno, 'area': area, 'abbr': abbr, 'ruolo': ruolo or sigla, 'sigla': sigla}
            )

    if sconosciuti:
        letta.avvisi.append('Nomi che non sono in "Collegamento Nomi": ' + ', '.join(sorted(sconosciuti)) + '.')
    if saltati:
        letta.avvisi.append('Caselle saltate perché non sono nomi: ' + ', '.join(sorted(saltati)) + '.')

    # il ruolo si scrive nella sigla solo dove l'area ne ha più d'uno (Impianto 1), come nella "Vista Dipendenti"
    ruoli_area = {}
    for riga in letta.layout:
        ruoli_area.setdefault(riga['area'], set()).add(riga['ruolo'].upper())
    for nome in ordine:
        turni = [_unisci_posti(posti.get((nome, i), []), nome, lunedi + timedelta(days=i), letta.avvisi, ruoli_area)
                 for i in range(7)]
        letta.righe.append(RigaDipendente(nome, turni))
    return letta


def _unisci_posti(lista, nome, giorno, avvisi, ruoli_area=None):
    """Le assegnazioni di una persona in un giorno diventano un solo turno: il primo posto
    (quello da Capo Turno, se c'è) decide fascia e postazione, gli altri si aggiungono al nome del posto."""
    if not lista:
        return CodiceTurno('', Fascia.RIPOSO)
    # "Piazzale - Pala" ripete il palista dell'impianto: se c'è già, non lo scrivo due volte
    pala = [a for a in lista if re.search(r'\bPALA\b', a['area'].upper())]
    if pala and len(lista) > len(pala):
        fasce_pal = {a['fascia'] for a in lista if a not in pala and a['sigla'].upper() == 'PAL'}
        lista = [a for a in lista if a not in pala or a['fascia'] not in fasce_pal]
    capo = [a for a in lista if a['sigla'].upper() == 'CT']
    principale = capo[0] if capo else lista[0]
    lista = [principale] + [a for a in lista if a is not principale]

    if len({a['fascia'] for a in lista}) > 1:
        sigle = ' e '.join(a['turno'] or '?' for a in lista)
        avvisi.append(f'{nome.title()} {giorno:%d/%m} è in due turni diversi ({sigle}): controlla.')

    # "Impianto 1 · Capo Turno e Palista + Sabbia - Sarco · Operatore di Linea"
    gruppi = {}
    for a in lista:
        etichetta = a['area'] if a['fascia'] == principale['fascia'] else f"{a['turno']} {a['area']}"
        ruoli = gruppi.setdefault(etichetta, [])
        if a['ruolo'] and a['ruolo'] not in ruoli:
            ruoli.append(a['ruolo'])
    posto = ' + '.join(f"{area} · {' e '.join(r)}" if r else area for area, r in gruppi.items())
    codice = f"{principale['turno']} · {posto}" if principale['turno'] else posto
    return CodiceTurno(
        sigla=_sigla_vista(principale, lista, ruoli_area or {}),
        codice=codice[:60],
        fascia=principale['fascia'],
        postazione=_postazione_area(principale['area'], principale['sigla']),
        capoturno=bool(capo),
        ruolo=principale['sigla'][:10],
        posto=posto[:200],
        # gli incarichi dello stesso turno (le pulizie seguono tutti); la "Pala" doppione è già tolta
        incarichi=' '.join(dict.fromkeys(
            f"{_postazione_area(a['area'])}/{a['sigla'].replace(' ', '')}" for a in lista
            if a['fascia'] == principale['fascia']))[:200],
    )


# ruoli che nella "Vista Dipendenti" si scrivono accanto all'area (gli altri si capiscono dall'area)
RUOLI_IN_VISTA = {'CT', 'PAL'}


def _sigla_vista(principale, lista, ruoli_area):
    """Come la casella della "Vista Dipendenti": "1T | Imp 1", "1T | Imp 1 | CT", "N | Imp 1 | CT + Pal",
    "2T | Imp 1 | Pal + Sab - Sar", "G | Met + Trasp"."""
    stessa = [a for a in lista if a['fascia'] == principale['fascia']]
    area = principale['abbr']
    piu_ruoli = len(ruoli_area.get(area, ())) > 1
    ruoli = [a['sigla'] for a in stessa
             if piu_ruoli and a['abbr'] == area and a['sigla'].upper() in RUOLI_IN_VISTA]
    altre = list(dict.fromkeys(a['abbr'] for a in stessa if a['abbr'] != area))
    ruoli = list(dict.fromkeys(ruoli))
    parti = [principale['turno']] if principale['turno'] else []
    if ruoli:
        parti += [area, ' + '.join(ruoli + altre)]
    else:
        parti.append(' + '.join([area] + altre))
    return ' | '.join(parti)


# ---------------------------------------------------------------- confronto nomi

def _token(nome):
    nome = re.sub(r"[’'`.]", ' ', (nome or '').upper())
    return [t for t in nome.split() if len(t) > 1]


def stesso_nome(a, b):
    """I nomi nel file non sono sempre scritti uguali: 'SPANO MAURO' / "SPANO' A. MAURO",
    'CARLO SAMMARTANO' / 'SAMMARTANO CARLO', 'DRAME BUOBA' / 'DRAME BOUBA'."""
    import difflib

    ta, tb = _token(a), _token(b)
    if not ta or not tb:
        return False
    sa, sb = set(ta), set(tb)
    if len(sa & sb) >= 2 and (sa <= sb or sb <= sa):
        return True
    return difflib.SequenceMatcher(None, ' '.join(sorted(ta)), ' '.join(sorted(tb))).ratio() >= 0.85


def trova_dipendente(nome, dipendenti):
    for d in dipendenti:
        if d.nome == nome.upper():
            return d
    for d in dipendenti:
        if stesso_nome(d.nome, nome):
            return d
    return None


# ---------------------------------------------------------------- salvataggio

def in_sessione(letta):
    """La settimana letta, in forma serializzabile per l'anteprima prima della conferma."""
    return {
        'lunedi': letta.lunedi.isoformat(),
        'foglio': letta.foglio,
        'avvisi': letta.avvisi,
        'righe': [
            [r.nome, [[t.codice, t.fascia, t.postazione, t.capoturno, t.ruolo, t.posto, t.incarichi, t.sigla]
                      for t in r.turni]]
            for r in letta.righe
        ],
        'note': letta.note,
        'tutor': letta.tutor,
        'layout': letta.layout,
    }


def da_sessione(dati):
    letta = SettimanaLetta(
        lunedi=date.fromisoformat(dati['lunedi']),
        foglio=dati['foglio'],
        note=[tuple(n) for n in dati['note']],
        tutor=dati['tutor'],
        avvisi=dati['avvisi'],
        layout=dati.get('layout', []),
    )
    letta.righe = [RigaDipendente(nome, [CodiceTurno(*t) for t in turni]) for nome, turni in dati['righe']]
    return letta


def salva_settimana(letta, utente=None, nome_file=''):
    """Crea o aggiorna la settimana. Ricaricare il file corretto a settimana iniziata
    aggiorna i turni senza perdere le pulizie già registrate.

    I turni modificati nell'app (cambi e ferie approvati) restano come sono: la terza
    lista restituita dice quali differivano dal file, per avvisare l'ufficio."""
    from django.db import transaction

    from django.utils import timezone

    from .models import Dipendente, ModificaTurno, NotaSettimana, Settimana, Turno
    from .richieste import ferie_approvate, segna_ferie_sui_turni

    oggi = timezone.localdate()
    lunedi_corrente = oggi - timedelta(days=oggi.weekday())
    # presa visione solo per i giorni da oggi a domenica della settimana prossima
    da_avvisare = (oggi, lunedi_corrente + timedelta(days=13))

    with transaction.atomic():
        settimana, _ = Settimana.objects.update_or_create(
            lunedi=letta.lunedi,
            defaults={'file_originale': nome_file, 'foglio': letta.foglio, 'caricata_da': utente},
        )
        dipendenti = list(Dipendente.objects.all())
        nuovi, visti, mantenuti = [], set(), []
        for riga in letta.righe:
            dip = trova_dipendente(riga.nome, dipendenti)
            if dip is None:
                from .mansioni import mansione_per

                dip = Dipendente.objects.create(nome=riga.nome, mansione=mansione_per(riga.nome) or 'OPERAIO')
                dipendenti.append(dip)
                nuovi.append(dip.nome)
            visti.add(dip.pk)
            esistenti = {t.data: t for t in Turno.objects.filter(dipendente=dip, data__in=settimana.giorni)}
            for giorno, t in zip(settimana.giorni, riga.turni):
                vecchio = esistenti.get(giorno)
                if vecchio and vecchio.nota_modifica:
                    # cambio turno o ferie approvati nell'app: hanno la precedenza sul file
                    if (vecchio.fascia, vecchio.postazione, vecchio.capoturno, vecchio.posto) != (
                            t.fascia, t.postazione, t.capoturno, t.posto):
                        mantenuti.append(f'{dip.nome_breve} {giorno:%d/%m}: {vecchio.descrizione} ({vecchio.nota_modifica})')
                    continue
                fascia = t.fascia
                if (vecchio and t.capoturno and fascia == Fascia.ALTRO and vecchio.capoturno
                        and vecchio.postazione == t.postazione and vecchio.fascia != Fascia.ALTRO):
                    fascia = vecchio.fascia  # Capo Turno: fascia già indicata nell'app
                prima = vecchio.descrizione if vecchio else None
                cambiato = vecchio and (vecchio.fascia, vecchio.postazione, vecchio.capoturno, vecchio.posto) != (
                    fascia, t.postazione, t.capoturno, t.posto)
                nuovo, _ = Turno.objects.update_or_create(
                    dipendente=dip,
                    data=giorno,
                    defaults={
                        'settimana': settimana,
                        'codice': t.codice,
                        'fascia': fascia,
                        'postazione': t.postazione,
                        'capoturno': t.capoturno,
                        'ruolo': t.ruolo,
                        'posto': t.posto,
                        'incarichi': t.incarichi,
                    },
                )
                if cambiato and da_avvisare[0] <= giorno <= da_avvisare[1]:
                    ModificaTurno.objects.create(dipendente=dip, data=giorno, prima=prima[:80], dopo=nuovo.descrizione[:80])
                ferie = ferie_approvate(dip, giorno)
                if ferie and nuovo.fascia != ferie.fascia:
                    segna_ferie_sui_turni(ferie, [nuovo])
                    mantenuti.append(f'{dip.nome_breve} {giorno:%d/%m}: {ferie.get_tipo_display()} approvate')
        # chi non è più nel file perde i turni della settimana, a meno che abbia già pulizie registrate
        settimana.turni.exclude(dipendente__in=visti).filter(pulizie__isnull=True, nota_modifica='').delete()

        settimana.note.all().delete()
        NotaSettimana.objects.bulk_create(
            NotaSettimana(settimana=settimana, riferimento=rif, dipendente=dip, testo=testo or '-', ordine=i)
            for i, (rif, dip, testo) in enumerate(letta.note)
        )
        for apprendista, tutor in letta.tutor.items():
            dip = trova_dipendente(apprendista, dipendenti)
            if dip and dip.tutor != tutor:
                dip.tutor = tutor
                dip.save(update_fields=['tutor'])
    return settimana, nuovi, mantenuti


# ---------------------------------------------------------------- elenco dipendenti (Giulia, 11/11/2026)

FOGLIO_ELENCO = 'Elenco Dipendenti, Aree e Orari'


def leggi_elenco_dipendenti(file):
    """I nomi del foglio «Elenco Dipendenti, Aree e Orari»: la colonna sotto l'intestazione «Dipendenti»."""
    wb = openpyxl.load_workbook(file, read_only=True, data_only=True)
    foglio = next((n for n in wb.sheetnames if pulisci(n).lower() == FOGLIO_ELENCO.lower()), None)
    if foglio is None:
        raise ValueError(f'Nel file non trovo il foglio «{FOGLIO_ELENCO}».')
    righe = list(wb[foglio].iter_rows(values_only=True))
    for i, riga in enumerate(righe[:15]):
        for j, valore in enumerate(riga):
            if pulisci(valore).lower() == 'dipendenti':
                intest = [pulisci(c).upper() for c in riga]
                col_mo = intest.index('MO') if 'MO' in intest else None
                elenco = {}
                for sotto in righe[i + 1:]:
                    nome = pulisci(sotto[j]) if j < len(sotto) else ''
                    if not nome:
                        continue
                    mo = sotto[col_mo] if col_mo is not None and col_mo < len(sotto) else None
                    try:
                        mo = int(mo) if mo not in (None, '') and int(mo) in (1, 2) else None
                    except (TypeError, ValueError):
                        mo = None
                    elenco.setdefault(nome.upper(), mo)
                return list(elenco.items())  # [(nome, livello macchine ottiche 1/2 o None)]
    raise ValueError(f'Nel foglio «{foglio}» non trovo la colonna «Dipendenti».')


def aggiorna_elenco_dipendenti(nomi):
    """Aggiunge all'app chi manca (i nomi scritti in modo diverso si riconoscono come per i turni).
    Restituisce (nuovi, già presenti)."""
    from .mansioni import mansione_per
    from .models import Dipendente

    dipendenti = list(Dipendente.objects.all())
    nuovi, presenti = [], []
    for voce in nomi:
        nome, mo = voce if isinstance(voce, tuple) else (voce, None)
        dip = trova_dipendente(nome, dipendenti)
        if dip is None:
            dip = Dipendente.objects.create(nome=nome, mansione=mansione_per(nome) or 'OPERAIO', livello_mo=mo)
            dipendenti.append(dip)
            nuovi.append(dip)
        else:
            if isinstance(voce, tuple) and dip.livello_mo != mo:
                dip.livello_mo = mo  # la competenza per le macchine ottiche segue il file
                dip.save(update_fields=['livello_mo'])
            presenti.append(dip)
    return nuovi, presenti
