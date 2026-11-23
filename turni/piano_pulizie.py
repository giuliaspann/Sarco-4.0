"""Pulizie per tutti (Giulia, 12/11/2026).

- Programma: per giorno (proposta A) e per settimana (S2), con i colori dei turni; chi deve fare cosa,
  dove e a che punto è. Per i giorni passati e oggi si leggono le pulizie vere, per i giorni futuri
  si calcolano dalle regole (senza scriverle), così si vede in anticipo chi farà le macchine ottiche.
- «In corso adesso» (timeline 4): i turni del giorno in ordine 1T, 2T, G, N; quello in corso è aperto.
- Scheda della pulizia: i passaggi (avviso, iniziata, manutentore, conclusa, ok del Capo Turno, convalida).
- Avvisi automatici: come nel file «Regole Pulizie - unico.xlsx» (21/11/2026), colonne «Avviso - minuti»,
  «Avviso - momento» e «Avviso - a chi». Il testo è sempre lo stesso schema; si ripete ogni 15 minuti finché
  nessuno risponde; i 3 tasti (Effettuata, Non effettuata, Ricordamelo tra) li usa solo chi conferma la pulizia.
  A fine turno, se la pulizia non è fatta, risulta Non eseguita (avvisati Capi Turno e responsabile piazzale).

Chi conferma e chi convalida: convalida sempre il responsabile piazzale (RP). All'Impianto 1 gli operatori
di linea non usano il telefono: conferma il Capo Turno (voci «CT_RP»). Negli altri reparti chi fa la pulizia
manda la conferma direttamente al RP.
"""

import logging
from datetime import datetime, timedelta

from django.db import IntegrityError
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .models import AvvisoPulizia, ElementoPulizia, Fascia, FASCE_LAVORATIVE, Pulizia, RegolaPulizia, Turno

log = logging.getLogger('turni.pulizie')

ORDINE = ['1T', '2T', 'G', 'N']
FASCE = {'1T': Fascia.MATTINA, '2T': Fascia.POMERIGGIO, 'G': Fascia.GIORNALIERO, 'N': Fascia.NOTTE}
NOMI = {'1T': ('1° turno', '6–14'), '2T': ('2° turno', '14–22'), 'G': ('Giornaliero', '8–17:30'), 'N': ('Notturno', '22–6')}
# stessi colori del calendario dell'app (.f-mattina, .f-pomeriggio, .f-giorno, .f-notte)
CLASSI = {'1T': 'f-mattina', '2T': 'f-pomeriggio', 'G': 'f-giorno', 'N': 'f-notte'}

AREE = [('IMP1', 'Impianto 1'), ('IMP2', 'Impianto 2'), ('SABBIA', 'Granella e Sabbia'), ('PIAZZALE', 'Piazzale e Metalli'),
        ('ALTRO', 'Manutenzione e mezzi')]
AREA_DI = {'IMP1': 'IMP1', 'IMP2': 'IMP2', 'BARROTTI': 'IMP2', 'SABBIA': 'SABBIA', 'SUPERBI': 'SABBIA', 'MULINO': 'SABBIA',
           'PIAZZALE': 'PIAZZALE', 'PALISTA': 'PIAZZALE', 'ROTOVAGLIO': 'PIAZZALE', 'METALLI': 'PIAZZALE'}

# stati come nelle proposte: colore e scritta
STATI = {
    'fare': 'Da fare', 'corso': 'In corso', 'ct': 'Al Capo Turno', 'rp': 'Inviata al RP', 'ok': 'Convalidata',
    'rifare': 'Da rifare', 'impedita': 'Non eseguibile', 'nonfatta': 'Non eseguita',
}
# nella riga di più persone vince lo stato che chiede ancora qualcosa
PRIORITA = ['rifare', 'impedita', 'nonfatta', 'fare', 'corso', 'ct', 'rp', 'ok']
RIPETI_OGNI = 15  # minuti tra un avviso e il successivo, finché nessuno risponde


def sigla(fascia):
    return '1T' if fascia in (Fascia.MATTINA, Fascia.ALTRO) else Turno.SIGLE.get(fascia, '')


def fasce_di(s):
    return [Fascia.MATTINA, Fascia.ALTRO] if s == '1T' else [FASCE[s]]


def area_di(turno, elemento=None):
    """L'area della pulizia: quella della voce (es. Rotovaglio = piazzale), altrimenti dove lavora la persona (es. la pala)."""
    luogo = getattr(elemento, 'luogo', '') or ''
    if luogo in AREA_DI:
        return AREA_DI[luogo]
    for p, _ in turno.lista_incarichi:
        if p in AREA_DI:
            return AREA_DI[p]
    luogo = getattr(elemento, 'luogo', '') or ''
    return AREA_DI.get(luogo, 'ALTRO')


def percorso(p):
    """Chi convalida: 'CT_RP' (prima l'ok del Capo Turno, poi il RP), 'PIAZZALE' (direttamente il RP) o 'NESSUNA'.
    Le pulizie del Capo Turno stesso (es. le straordinarie) vanno direttamente al RP."""
    C = ElementoPulizia.Convalida
    if p.elemento_id and p.elemento.convalida == C.NESSUNA:
        return 'NESSUNA'
    if p.turno.capoturno or not p.elemento_id:
        return 'PIAZZALE'
    return 'CT_RP' if p.elemento.convalida in (C.CT_RP, C.CT) else 'PIAZZALE'


def va_al_rp(p):
    """La pulizia aspetta adesso la convalida del responsabile piazzale?"""
    if p.stato != Pulizia.Stato.FATTA:
        return False
    via = percorso(p)
    return via == 'PIAZZALE' or (via == 'CT_RP' and bool(p.ok_capoturno_il))


Q_AL_RP = (Q(elemento__convalida=ElementoPulizia.Convalida.PIAZZALE)
           | Q(elemento__convalida=ElementoPulizia.Convalida.CT_RP, ok_capoturno_il__isnull=False)
           | Q(elemento__isnull=True))


def stato_di(p):
    S = Pulizia.Stato
    if p.stato == S.VERIFICATA:
        return 'ok'
    if p.stato == S.SEGNALATA:
        return 'rifare'
    if p.stato == S.IMPEDITA:
        return 'impedita'
    if p.stato == S.NON_ESEGUITA:
        return 'nonfatta'
    if p.stato == S.FATTA:
        return 'rp' if va_al_rp(p) or percorso(p) == 'NESSUNA' else 'ct'
    return 'corso' if p.iniziata_il else 'fare'


def stato_gruppo(stati):
    return next((s for s in PRIORITA if s in stati), 'fare')


def quando_di(e, turno=None):
    """La riga piccola sotto il nome: quando si fa o quando arriva l'avviso."""
    A = ElementoPulizia.Avviso
    if e is None:
        return ''
    if e.avviso == A.META:
        return 'a metà turno'
    if e.avviso == A.DOPO_INIZIO and e.avviso_minuti:
        return f"avviso {e.avviso_minuti} min dopo l'inizio del turno"
    if e.avviso == A.DOPO_META and e.avviso_minuti:
        return f'avviso {e.avviso_minuti} min dopo metà turno'
    if e.avviso == A.ENTRO and e.avviso_ora:
        return f'entro le {e.avviso_ora:%H:%M}'
    if e.avviso == A.ORA and e.avviso_ora:
        return f'avviso alle {e.avviso_ora:%H:%M}'
    if e.avviso == A.PRIMA and e.avviso_minuti:
        return f'avviso {e.avviso_minuti} min prima della fine'
    if e.minuti_prima_fine:
        return f'ultimi {e.minuti_prima_fine} min del turno'
    return ''


def _turni_del_giorno(giorno):
    return [t for t in Turno.objects.filter(data=giorno, settimana__pubblicata=True, dipendente__attivo=True,
                                            fascia__in=FASCE_LAVORATIVE).select_related('dipendente').order_by('dipendente__nome')
            if t.lavora and sigla(t.fascia) in ORDINE]


def _nome(t):
    return t.dipendente.nome_breve


def piano_giorno(giorno, oggi=None):
    """Le voci di pulizia del giorno, raggruppate per turno: {'1T': [voce, ...], ...}.
    Voce = nome, area, persone, stato, pk della prima pulizia (per aprire la scheda), quando."""
    from .pulizie import genera_pulizie

    oggi = oggi or timezone.localdate()
    turni = _turni_del_giorno(giorno)
    voci = {}

    def aggiungi(s, chiave, nome, icona, area, elemento, persona, stato, pk=None, straordinaria=False):
        v = voci.setdefault((s, chiave), {
            'sigla': s, 'nome': nome, 'icona': icona, 'area': area, 'area_nome': dict(AREE).get(area, ''),
            'elemento': elemento, 'persone': [], 'stati': [], 'pk': pk, 'quando': quando_di(elemento),
            'straordinaria': straordinaria,
            'settimanale': bool(elemento and elemento.regole.filter(Q(giorno__isnull=False) | Q(ultimo_settimana=True)).exists()),
        })
        if persona and persona not in v['persone']:
            v['persone'].append(persona)
        v['stati'].append(stato)
        if pk and not v['pk']:
            v['pk'] = pk

    if giorno <= oggi:
        if giorno >= oggi - timedelta(days=1):
            for t in turni:
                genera_pulizie(t)  # oggi (e la notte di ieri): le pulizie vere, come in «Pulizia»
        for p in (Pulizia.objects.filter(turno__data=giorno).select_related('elemento', 'turno__dipendente', 'fatta_da')
                  .order_by('elemento__ordine', 'elemento__nome', 'pk')):
            s = sigla(p.turno.fascia)
            if s not in ORDINE:
                continue
            chi = p.fatta_da.nome_breve if p.fatta_da_id else _nome(p.turno)
            if p.elemento_id:
                aggiungi(s, f'e{p.elemento_id}-{area_di(p.turno, p.elemento)}', p.elemento.nome, p.elemento.icona,
                         area_di(p.turno, p.elemento), p.elemento, chi, stato_di(p), p.pk)
            else:
                aggiungi(s, f'p{p.pk}', p.titolo, '🧹', area_di(p.turno), None, chi, stato_di(p), p.pk, straordinaria=True)
    else:
        regole = list(RegolaPulizia.objects.filter(elemento__attivo=True, elemento__promemoria=False).select_related('elemento'))
        for t in turni:
            if t.capoturno:
                continue  # i Capi Turno non hanno pulizie loro: supervisionano
            for r in regole:
                if r.corrisponde(t) and r.si_applica(t):
                    e = r.elemento
                    area = area_di(t, e)
                    aggiungi(sigla(t.fascia), f'e{e.pk}-{area}', e.nome, e.icona, area, e, _nome(t), 'fare')
        for p in Pulizia.objects.filter(turno__data=giorno, elemento__isnull=True).select_related('turno__dipendente'):
            aggiungi(sigla(p.turno.fascia), f'p{p.pk}', p.titolo, '🧹', area_di(p.turno), None, _nome(p.turno), stato_di(p), p.pk,
                     straordinaria=True)
    # i controlli con promemoria (vagli zig-zag): li fa il manutentore, li segue il Capo Turno
    gia = {v['elemento'].pk for v in voci.values() if v['elemento']}
    for r in RegolaPulizia.objects.filter(elemento__attivo=True, elemento__promemoria=True).select_related('elemento'):
        e = r.elemento
        if e.pk in gia:
            continue
        for t in turni:
            if r.corrisponde(t):
                aggiungi(sigla(t.fascia), f'e{e.pk}-{AREA_DI.get(e.luogo, "ALTRO")}', e.nome, e.icona, AREA_DI.get(e.luogo, 'ALTRO'), e,
                         'Capo Turno + manutentore', 'fare')
                gia.add(e.pk)
                break
    per_turno = {s: [] for s in ORDINE}
    ordine_aree = [a for a, _ in AREE]
    for v in voci.values():
        v['stato'] = stato_gruppo(v['stati'])
        v['stato_nome'] = STATI[v['stato']]
        per_turno[v['sigla']].append(v)
    for s in per_turno:
        per_turno[s].sort(key=lambda v: (ordine_aree.index(v['area']) if v['area'] in ordine_aree else 9,
                                         v['elemento'].ordine if v['elemento'] else 99, v['nome']))
    return per_turno


def conteggi(voci):
    fatte = sum(v['stato'] == 'ok' for v in voci)
    in_corso = sum(v['stato'] in ('corso', 'ct', 'rp') for v in voci)
    return {'tot': len(voci), 'ok': fatte, 'avanti': fatte + in_corso}


# ---------------------------------------------------------------- avvisi automatici

def momento(e, rif):
    """Quando parte l'avviso della voce per il turno di riferimento (None = senza avviso)."""
    A = ElementoPulizia.Avviso
    inizio, fine = rif.inizio, rif.fine
    if e.avviso == A.META:
        return inizio + (fine - inizio) / 2
    if e.avviso == A.DOPO_META:
        return inizio + (fine - inizio) / 2 + timedelta(minutes=e.avviso_minuti or 0)
    if e.avviso == A.DOPO_INIZIO:
        return inizio + timedelta(minutes=e.avviso_minuti or 0)
    if e.avviso == A.PRIMA and e.avviso_minuti:
        return fine - timedelta(minutes=e.avviso_minuti)
    if e.avviso in (A.ORA, A.ENTRO) and e.avviso_ora:
        quando = timezone.make_aware(datetime.combine(rif.data, e.avviso_ora))
        return quando + timedelta(days=1) if quando < inizio else quando
    return None


def capi(turni, e):
    from .pulizie import POSTAZIONI_AREA

    tutti = [t for t in turni if t.capoturno]
    vicini = [t for t in tutti if t.postazione in POSTAZIONI_AREA.get(e.luogo, [e.luogo])]
    return vicini or tutti


def destinatari(e, turni, righe):
    """Chi riceve l'avviso, come nella colonna «Avviso - a chi»: [(utente_id, con_tasti)].
    I 3 tasti li ha solo chi conferma la pulizia; gli altri lo ricevono solo per sapere (es. vagli: il Capo Turno)."""
    from .pulizie import manutentore_del_turno

    A = ElementoPulizia.AvvisoA
    chi = []
    if e.avviso_a in (A.CT, A.CT_MAN):
        # il Capo Turno ha i tasti quando conferma lui (OdL dell'Impianto 1, ottiche, notturne)
        tasti_ct = e.avviso_a == A.CT
        chi += [(t.dipendente.utente_id, tasti_ct) for t in capi(turni, e)]
    if e.avviso_a == A.CT_MAN:
        con_pulizia = [p.turno.dipendente.utente_id for p in righe]
        if con_pulizia:
            chi += [(u, True) for u in con_pulizia]
        elif turni:
            m = manutentore_del_turno(turni[0])
            if m:
                chi.append((m.dipendente.utente_id, True))
    if e.avviso_a in (A.ADDETTI, A.MAN):
        chi += [(p.turno.dipendente.utente_id, True) for p in righe]
    visti, out = set(), []
    for u, tasti in sorted(chi, key=lambda x: not x[1]):  # se uno compare due volte vince «con i tasti»
        if u and u not in visti:
            visti.add(u)
            out.append((u, tasti))
    return out


def nome_corto(e):
    return 'ottiche' if e and e.con_avvio else (e.nome.lower() if e else '')


def cosa_completare(e):
    """Come nella formula del file: dal tasto della pulizia."""
    t = (e.tasto or '').lower()
    if 'ingrassaggio' in t:
        return "l'ingrassaggio e la pulizia"
    if 'controllo' in t or e.controllo:
        return 'il controllo'
    return 'la pulizia'


def quando_testo(e):
    A = ElementoPulizia.Avviso
    m = e.avviso_minuti or 0
    if e.avviso == A.PRIMA:
        return f'mancano {m} min alla fine del turno'
    if e.avviso == A.DOPO_META:
        return f'sono passati {m} min da metà turno'
    if e.avviso == A.DOPO_INIZIO:
        return f"sono passati {m} min dall'inizio del turno"
    if e.avviso == A.META:
        return 'è metà turno'
    if e.avviso_ora:
        return f'sono le {e.avviso_ora:%H:%M}'
    return ''


def testi(e, righe=None):
    """Il testo dell'avviso, uguale per tutte le voci (colonna «Avviso - testo» del file):
    «🔔 Linea Scarto: mancano 15 min alla fine del turno: completa la pulizia.» → (titolo, testo)."""
    q = quando_testo(e)
    return f'🔔 {e.nome}', f'{q[:1].upper()}{q[1:]}: completa {cosa_completare(e)}.'


def chiave_avviso(p):
    return f'{p.elemento_id}-{p.turno.data.isoformat()}-{sigla(p.turno.fascia)}'


def _manda(e, turni, righe, url_di):
    from . import push

    titolo, testo = testi(e, righe)
    p0 = righe[0] if righe else None
    url = url_di(p0)
    for u, _tasti in destinatari(e, turni, righe):
        push.invia([u], titolo, testo, url, tipo='avviso_pulizia', oggetto_id=p0.pk if p0 else None)


def controlla(adesso=None):
    """Manda gli avvisi delle pulizie arrivati all'ora giusta, li ripete ogni 15 minuti finché la pulizia non è fatta
    (o rimandata con «Ricordamelo tra») e a fine turno segna Non eseguite quelle rimaste da fare.
    Lo chiama ogni minuto il controllo in background (apps.py) o il comando «avvisi_pulizie»."""
    from .pulizie import _al_manutentore, genera_pulizie

    adesso = adesso or timezone.now()
    oggi = timezone.localdate(adesso)
    mandati = 0
    voci = list(ElementoPulizia.objects.filter(attivo=True).exclude(avviso='').prefetch_related('regole'))

    def url_di(p):
        return reverse('turni:avviso_pulizia', args=[p.pk]) if p else reverse('turni:pulizie_adesso')

    for giorno in (oggi - timedelta(days=1), oggi):
        for s in ORDINE:
            turni = [t for t in Turno.objects.filter(data=giorno, fascia__in=fasce_di(s), settimana__pubblicata=True,
                                                     dipendente__attivo=True).select_related('dipendente') if t.lavora]
            if not turni:
                continue
            rif = next((t for t in turni if t.fascia == FASCE[s]), turni[0])
            if adesso >= rif.fine:
                mandati += chiudi_turno(giorno, s, adesso)
                continue
            if adesso < rif.inizio:
                continue
            for e in voci:
                quando = momento(e, rif)
                if quando is None or adesso < quando:
                    continue
                regole = list(e.regole.all())
                if regole and not any(r.corrisponde(t) for r in regole for t in turni):
                    continue
                if e.promemoria:
                    _al_manutentore(e, rif)
                elif regole:
                    for t in turni:
                        genera_pulizie(t)
                righe = list(Pulizia.objects.filter(elemento=e, turno__data=giorno, turno__fascia__in=fasce_di(s))
                             .select_related('turno__dipendente', 'elemento'))
                if not regole and not righe:
                    continue  # voce senza regole (Generiche Notturne): solo se qualcuno l'ha assegnata
                da_fare = [p for p in righe if p.stato in (Pulizia.Stato.DA_FARE, Pulizia.Stato.SEGNALATA)]
                chiave = f'{e.pk}-{giorno.isoformat()}-{s}'
                a = AvvisoPulizia.objects.filter(chiave=chiave).first()
                if a is None:
                    try:
                        a = AvvisoPulizia.objects.create(chiave=chiave, ultimo_il=adesso)
                    except IntegrityError:
                        continue  # l'ha già mandato l'altro processo
                    if righe and not da_fare:
                        continue  # già fatta: niente da ricordare
                    _manda(e, turni, da_fare or righe, url_di)
                    mandati += 1
                    continue
                if not da_fare:
                    continue
                # ripetizione: alla fine del rinvio («Ricordamelo tra»), altrimenti ogni 15 minuti
                if a.rimanda_al:
                    if adesso < a.rimanda_al:
                        continue
                elif a.ultimo_il and adesso < a.ultimo_il + timedelta(minutes=RIPETI_OGNI):
                    continue
                n = AvvisoPulizia.objects.filter(pk=a.pk, ultimo_il=a.ultimo_il, rimanda_al=a.rimanda_al).update(
                    ultimo_il=adesso, rimanda_al=None)
                if n:  # un solo processo manda la ripetizione
                    _manda(e, turni, da_fare, url_di)
                    mandati += 1
    return mandati


def chiudi_turno(giorno, s, adesso):
    """Fine turno: le pulizie con avviso ancora da fare diventano Non eseguite; avvisati i Capi Turno in servizio e il RP.
    Solo per i turni finiti da poco (6 ore), così le pulizie vecchie restano come sono."""
    from . import manutenzione as mn
    from .pulizie import resp_piazzale

    righe = list(Pulizia.objects.filter(turno__data=giorno, turno__fascia__in=fasce_di(s), stato=Pulizia.Stato.DA_FARE,
                                        elemento__isnull=False).exclude(elemento__avviso='')
                 .select_related('turno__dipendente', 'elemento'))
    chiuse = 0
    for p in righe:
        if not (p.turno.fine <= adesso < p.turno.fine + timedelta(hours=6)):
            continue
        if not Pulizia.objects.filter(pk=p.pk, stato=Pulizia.Stato.DA_FARE).update(stato=Pulizia.Stato.NON_ESEGUITA):
            continue
        chiuse += 1
        mn.avvisa(mn.capiturno_oggi() + resp_piazzale(), None, f'⏱️ {p.titolo}: non eseguita',
                  f'{p.turno.dipendente.nome_breve} · {NOMI.get(s, ("", ""))[0]} del {giorno:%d/%m}: a fine turno non risultava fatta.',
                  reverse('turni:pulizia_voce', args=[p.pk]))
    return chiuse


def avvia_controllo():
    """Ogni minuto, in un thread del server: gli avvisi partono anche se nessuno apre l'app."""
    import threading
    import time

    from django.db import close_old_connections

    def giro():
        time.sleep(20)
        while True:
            try:
                controlla()
            except Exception:
                log.exception('Avvisi pulizie: controllo non riuscito')
            finally:
                close_old_connections()
            time.sleep(60)

    threading.Thread(target=giro, name='avvisi-pulizie', daemon=True).start()
