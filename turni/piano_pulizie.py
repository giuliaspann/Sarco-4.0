"""Pulizie per tutti (Giulia, 12/11/2026).

- Programma: per giorno (proposta A) e per settimana (S2), con i colori dei turni; chi deve fare cosa,
  dove e a che punto è. Per i giorni passati e oggi si leggono le pulizie vere, per i giorni futuri
  si calcolano dalle regole (senza scriverle), così si vede in anticipo chi farà le macchine ottiche.
- «In corso adesso» (timeline 4): i turni del giorno in ordine 1T, 2T, G, N; quello in corso è aperto.
- Scheda della pulizia: i passaggi (avviso, iniziata, manutentore, conclusa, ok del Capo Turno, convalida).
- Avvisi automatici: ottiche a metà turno, pozzetti entro le 7, vagli 45 minuti prima della fine,
  Incolore 1:15 prima della fine, carrelli alle 16 (campi «avviso» delle voci di pulizia).

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

AREE = [('IMP1', 'Impianto 1'), ('IMP2', 'Impianto 2'), ('SABBIA', 'Sabbia'), ('PIAZZALE', 'Piazzale e Metalli'),
        ('ALTRO', 'Manutenzione e mezzi')]
AREA_DI = {'IMP1': 'IMP1', 'IMP2': 'IMP2', 'BARROTTI': 'IMP2', 'SABBIA': 'SABBIA', 'SUPERBI': 'SABBIA', 'MULINO': 'SABBIA',
           'PIAZZALE': 'PIAZZALE', 'PALISTA': 'PIAZZALE', 'ROTOVAGLIO': 'PIAZZALE', 'METALLI': 'PIAZZALE'}

# stati come nelle proposte: colore e scritta
STATI = {
    'fare': 'Da fare', 'corso': 'In corso', 'ct': 'Al Capo Turno', 'rp': 'Inviata al RP', 'ok': 'Convalidata',
    'rifare': 'Da rifare', 'impedita': 'Non eseguibile',
}
# nella riga di più persone vince lo stato che chiede ancora qualcosa
PRIORITA = ['rifare', 'impedita', 'fare', 'corso', 'ct', 'rp', 'ok']


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
           | Q(elemento__isnull=True, turno__capoturno=True))


def stato_di(p):
    S = Pulizia.Stato
    if p.stato == S.VERIFICATA:
        return 'ok'
    if p.stato == S.SEGNALATA:
        return 'rifare'
    if p.stato == S.IMPEDITA:
        return 'impedita'
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
            'straordinaria': straordinaria, 'settimanale': bool(elemento and elemento.regole.filter(giorno__isnull=False).exists()),
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
    from .pulizie import manutentore_del_turno

    A = ElementoPulizia.AvvisoA
    ids = []
    if e.avviso_a in (A.CT, A.CT_MAN):
        ids += [t.dipendente.utente_id for t in capi(turni, e)]
    if e.avviso_a in (A.CT_MAN, A.MAN) and turni:
        m = manutentore_del_turno(turni[0])
        if m:
            ids.append(m.dipendente.utente_id)
    if e.avviso_a in (A.ADDETTI, A.MAN):
        ids += [p.turno.dipendente.utente_id for p in righe]
    return [i for i in dict.fromkeys(ids) if i]


def nome_corto(e):
    return e.nome.split()[-1].lower() if e.con_avvio else e.nome.lower()


def testi(e, righe):
    A = ElementoPulizia.Avviso
    if e.avviso == A.META:
        return f'🔔 {e.nome}: è metà turno', f'Quando cominciate tocca «Pulizia {nome_corto(e)} iniziata».'
    if e.avviso == A.ENTRO:
        return f'🔔 {e.nome}: sono stati puliti?', f'Alle {e.avviso_ora:%H:%M} non risultano ancora fatti: rispondi e indica chi li ha puliti.'
    if e.avviso == A.PRIMA:
        cosa = 'il controllo' if e.controllo else 'la pulizia'
        return f'🔔 {e.nome}: mancano {e.avviso_minuti} minuti alla fine del turno', f'È ora di fare {cosa} e mandare la conferma con la foto.'
    return f'🔔 {e.nome}', f'Sono le {e.avviso_ora:%H:%M}: è ora di {e.nome.lower()}.'


def controlla(adesso=None):
    """Manda gli avvisi delle pulizie arrivati all'ora giusta (una volta sola per voce, giorno e turno).
    Lo chiama ogni minuto il controllo in background (apps.py) o il comando «avvisi_pulizie»."""
    from . import push
    from .pulizie import _al_manutentore, genera_pulizie

    adesso = adesso or timezone.now()
    oggi = timezone.localdate(adesso)
    mandati = 0
    voci = list(ElementoPulizia.objects.filter(attivo=True).exclude(avviso='').prefetch_related('regole'))
    if not voci:
        return 0
    for giorno in (oggi - timedelta(days=1), oggi):
        for s in ORDINE:
            turni = [t for t in Turno.objects.filter(data=giorno, fascia__in=fasce_di(s), settimana__pubblicata=True,
                                                     dipendente__attivo=True).select_related('dipendente') if t.lavora]
            if not turni:
                continue
            rif = next((t for t in turni if t.fascia == FASCE[s]), turni[0])
            if not (rif.inizio <= adesso < rif.fine):
                continue
            for e in voci:
                quando = momento(e, rif)
                if quando is None or adesso < quando:
                    continue
                chiave = f'{e.pk}-{giorno.isoformat()}-{s}'
                if AvvisoPulizia.objects.filter(chiave=chiave).exists():
                    continue
                if not any(r.corrisponde(t) for r in e.regole.all() for t in turni):
                    continue
                if e.promemoria:
                    _al_manutentore(e, rif)
                else:
                    for t in turni:
                        genera_pulizie(t)
                righe = list(Pulizia.objects.filter(elemento=e, turno__data=giorno, turno__fascia__in=fasce_di(s))
                             .select_related('turno__dipendente', 'elemento'))
                fatte = righe and all(p.stato != Pulizia.Stato.DA_FARE for p in righe)
                try:
                    AvvisoPulizia.objects.create(chiave=chiave)
                except IntegrityError:
                    continue  # l'ha già mandato l'altro processo
                if fatte:
                    continue  # già fatta: niente da ricordare
                titolo, testo = testi(e, righe)
                url = reverse('turni:pulizia_voce', args=[righe[0].pk]) if righe else reverse('turni:pulizie_adesso')
                push.invia(destinatari(e, turni, righe), titolo, testo, url, tipo='avviso_pulizia',
                           oggetto_id=righe[0].pk if righe else None)
                mandati += 1
    return mandati


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
