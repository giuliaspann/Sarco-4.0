"""Calendario (Giulia, 11–12/11/2026), layout D scelto su Claude Design.

- Ogni dipendente, nel profilo, ha «Calendario»: settimana (si apre così) o mese, con il proprio turno
  (colore, area, CT), le riunioni a cui è invitato, le proprie visite mediche, corsi e scadenze,
  i compleanni di tutti, i fermi impianto programmati e i giorni rossi.
- L'ufficio e il responsabile impianto (RI) vedono anche il «calendario di tutti»: visite, corsi e scadenze
  di tutti, riunioni, fermi, pulizie e manutenzioni programmate, compleanni. Il responsabile piazzale no.
"""

import calendar
from datetime import date, timedelta
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import format as formatta

from .models import Comunicazione, Dipendente, Intervento, InvitoRiunione, Pulizia, Riunione, Scadenza, Turno

# tipo: (nome, classe del colore)
TIPI = {
    'riunione': ('Riunione', 'cal-blu'),
    'fermo': ('Fermo impianto', 'cal-grigio'),
    'visita': ('Visita medica', 'cal-viola'),
    'corso': ('Corso', 'cal-acqua'),
    'scadenza': ('Scadenza', 'cal-rosso'),
    'compleanno': ('Compleanno', 'cal-arancio'),
    'pulizia': ('Pulizia', 'cal-verde'),
    'manutenzione': ('Manutenzione', 'cal-ambra'),
    'festa': ('Festività', 'cal-festa'),
}
# nella colonna stretta della settimana: icona + poche lettere
ICONE = {'visita': '🩺', 'corso': '🎓', 'scadenza': '⚠️'}
# i tipi che hanno un filtro nel calendario di tutti (le festività si vedono sempre)
FILTRABILI = ['visita', 'corso', 'scadenza', 'riunione', 'fermo', 'pulizia', 'manutenzione', 'compleanno']


# ---------------------------------------------------------------- giorni rossi

def pasqua(anno):
    """Domenica di Pasqua (calendario gregoriano, metodo anonimo)."""
    a, b, c = anno % 19, anno // 100, anno % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    lz = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lz) // 451
    mese = (h + lz - 7 * m + 114) // 31
    giorno = (h + lz - 7 * m + 114) % 31 + 1
    return date(anno, mese, giorno)


def festivi(anno):
    """{data: nome} delle feste nazionali italiane."""
    p = pasqua(anno)
    feste = {
        date(anno, 1, 1): 'Capodanno', date(anno, 1, 6): 'Epifania', p: 'Pasqua', p + timedelta(days=1): 'Pasquetta',
        date(anno, 4, 25): 'Festa della Liberazione', date(anno, 5, 1): 'Festa del Lavoro',
        date(anno, 6, 2): 'Festa della Repubblica', date(anno, 8, 15): 'Ferragosto', date(anno, 11, 1): 'Ognissanti',
        date(anno, 12, 8): 'Immacolata', date(anno, 12, 25): 'Natale', date(anno, 12, 26): 'Santo Stefano',
    }
    if anno >= 2026:  # San Francesco torna festa nazionale dal 2026
        feste[date(anno, 10, 4)] = 'San Francesco'
    return feste


def festivi_tra(dal, al):
    tutte = {}
    for anno in range(dal.year, al.year + 1):
        tutte.update(festivi(anno))
    return {g: n for g, n in tutte.items() if dal <= g <= al}


# ---------------------------------------------------------------- chi vede cosa

def vede_tutti(utente):
    """Ufficio e responsabile impianto (RI): calendario di tutti, con visite e scadenze di ognuno."""
    from .richieste import e_responsabile

    if not utente.is_authenticated:
        return False
    dip = getattr(utente, 'dipendente', None)
    return bool(utente.is_staff or (dip and dip.resp_impianto) or (dip is None and e_responsabile(utente)))


puo_vedere = vede_tutti


# ---------------------------------------------------------------- eventi

def _evento(tipo, giorno, titolo, sotto='', url='', ora='', breve=''):
    nome, classe = TIPI[tipo]
    return {'tipo': tipo, 'nome_tipo': nome, 'classe': classe, 'giorno': giorno, 'titolo': titolo, 'sotto': sotto,
            'url': url, 'ora': ora, 'breve': breve or titolo}


def corto(dip):
    """'Alagna G.': il nome sta nella colonna stretta della settimana."""
    parole = dip.nome_breve.split()
    return f'{" ".join(parole[:-1])} {parole[-1][0]}.' if len(parole) > 1 else dip.nome_breve


def _tipo_scadenza(s):
    return {Scadenza.Tipo.VISITA: 'visita', Scadenza.Tipo.CORSO: 'corso'}.get(s.tipo, 'scadenza')


def _compleanno(nascita, anno):
    try:
        return nascita.replace(year=anno)
    except ValueError:  # nato il 29 febbraio
        return date(anno, 2, 28)


def eventi(utente, dal, al, tutti=True, dip=None):
    """{giorno: [eventi]} tra dal e al compresi.
    tutti=True: il calendario di tutti (ufficio, RI). tutti=False: quello personale di dip."""
    per_giorno = {}

    def metti(e):
        if dal <= e['giorno'] <= al:
            per_giorno.setdefault(e['giorno'], []).append(e)

    # riunioni: tutte per l'ufficio, solo le proprie (non rifiutate) per il dipendente
    if tutti:
        riunioni = [(r, '') for r in Riunione.objects.filter(annullata=False, inizio__date__range=(dal, al))]
    else:
        riunioni = [(i.riunione, i.get_risposta_display()) for i in InvitoRiunione.objects.filter(
            dipendente=dip, riunione__annullata=False, riunione__inizio__date__range=(dal, al)).exclude(
            risposta=InvitoRiunione.Risposta.NO).select_related('riunione')]
    for r, risposta in riunioni:
        i, f = timezone.localtime(r.inizio), timezone.localtime(r.fine)
        sotto = f'{i:%H:%M}–{f:%H:%M} · {r.luogo}' + (f' · {risposta.lower()}' if risposta else '')
        metti(_evento('riunione', i.date(), r.titolo, sotto, reverse('turni:riunione', args=[r.pk]), f'{i:%H:%M}',
                      f'👥 {i:%H:%M}'))

    # fermi impianto programmati (li vedono tutti)
    for c in Comunicazione.objects.filter(tipo=Comunicazione.Tipo.FERMO, dal__isnull=False, dal__date__lte=al).exclude(
            al__date__lt=dal):
        inizio, fine = timezone.localtime(c.dal), timezone.localtime(c.al or c.dal)
        dove = c.get_luogo_display() if c.luogo else 'Impianto'
        motivo = f' · {c.get_motivo_display().lower()}' if c.motivo else ''
        g = inizio.date()
        while g <= fine.date():
            metti(_evento('fermo', g, f'{dove} fermo{motivo}', f'{inizio:%H:%M}–{fine:%H:%M} · {c.testo[:80]}',
                          reverse('turni:comunicazione', args=[c.pk]), f'{inizio:%H:%M}' if g == inizio.date() else '',
                          f'⛔ {Turno.SIGLE_POSTAZIONE.get(c.luogo) or dove}'))
            g += timedelta(days=1)

    if tutti:
        for p in Pulizia.objects.filter(richiesta_da__isnull=False, turno__data__range=(dal, al)).select_related(
                'turno__dipendente', 'elemento'):
            metti(_evento('pulizia', p.turno.data, p.titolo, f'{p.turno.descrizione_fascia} · {p.turno.dipendente.nome_breve}'
                          f' · {p.get_stato_display().lower()}', reverse('turni:capoturno') + f'?giorno={p.turno.data.isoformat()}',
                          breve=f'🧹 {p.titolo}'))
        for i in Intervento.objects.filter(tipo=Intervento.Tipo.PROGRAMMATA, da_fare_il__range=(dal, al)).exclude(
                stato=Intervento.Stato.RIFIUTATA).select_related('macchina'):
            metti(_evento('manutenzione', i.da_fare_il, i.macchina.nome, f'{i.descrizione[:80]} · {i.get_stato_display().lower()}',
                          reverse('turni:intervento', args=[i.pk]), breve=f'🔧 {i.macchina.nome}'))

    # visite mediche, corsi e scadenze: di tutti per ufficio e RI, le proprie per il dipendente
    scadenze = Scadenza.objects.filter(chiusa_il__isnull=True, scade_il__range=(dal, al)).select_related('dipendente')
    if tutti:
        scadenze = scadenze.filter(dipendente__attivo=True) if vede_tutti(utente) else scadenze.none()
    else:
        scadenze = scadenze.filter(dipendente=dip) if dip else scadenze.none()
    for s in scadenze:
        tipo = _tipo_scadenza(s)
        nome = s.get_tipo_display()
        if tutti:
            breve = ICONE[tipo] + f' {corto(s.dipendente)}'
            metti(_evento(tipo, s.scade_il, f'{nome} · {s.dipendente.nome_breve}', s.descrizione or 'scadenza',
                          reverse('turni:scadenze') + f'?q={s.dipendente.nome}', breve=breve))
        else:
            metti(_evento(tipo, s.scade_il, nome, s.descrizione or s.note, breve=ICONE[tipo] + ' ' + {'visita': 'Visita', 'corso': 'Corso'}.get(tipo, 'Scade')))

    # compleanni di tutti
    for d in Dipendente.objects.filter(attivo=True, data_nascita__isnull=False):
        for anno in range(dal.year, al.year + 1):
            g = _compleanno(d.data_nascita, anno)
            if dip and d.pk == dip.pk:
                metti(_evento('compleanno', g, 'Buon compleanno!', breve='🎂 Tu!'))
            else:
                metti(_evento('compleanno', g, f'Compleanno di {d.nome_breve}', breve=f'🎂 {corto(d)}'))

    for g, nome in festivi_tra(dal, al).items():
        metti(_evento('festa', g, nome))

    for lista in per_giorno.values():
        lista.sort(key=lambda e: (e['tipo'] != 'festa', e['ora'] or '99', e['tipo']))
    return per_giorno


def eventi_prossimi(utente, giorni):
    """Quanti eventi nei prossimi giorni (per il numerino sulla home dell'ufficio), senza feste e compleanni."""
    if not vede_tutti(utente):
        return 0
    oggi = timezone.localdate()
    tutti = eventi(utente, oggi, oggi + timedelta(days=giorni - 1))
    return sum(1 for v in tutti.values() for e in v if e['tipo'] not in ('festa', 'compleanno'))


# ---------------------------------------------------------------- settimana / mese

def _data(testo):
    try:
        return date.fromisoformat(testo or '')
    except ValueError:
        return None


def contesto(request, dip=None, tutti=False):
    """Tutto quello che serve a _calendario_d.html: vista (settimana o mese), griglia, giorno scelto, filtri."""
    oggi = timezone.localdate()
    g = request.GET
    vista = g.get('vista') or ('mese' if g.get('mese') else 'settimana')
    vista = 'mese' if vista == 'mese' else 'settimana'
    giorno = _data(g.get('giorno'))

    if vista == 'mese':
        try:
            anno, mese = (int(x) for x in (g.get('mese') or '').split('-'))
            primo = date(anno, mese, 1)
        except (ValueError, TypeError):
            primo = (giorno or oggi).replace(day=1)
        righe = calendar.Calendar(firstweekday=0).monthdatescalendar(primo.year, primo.month)
        dentro = lambda d: (d.year, d.month) == (primo.year, primo.month)  # noqa: E731
        prec, succ = (primo - timedelta(days=1)).replace(day=1), (primo + timedelta(days=32)).replace(day=1)
        param = 'mese'
        valore = lambda d: f'{d:%Y-%m}'  # noqa: E731
        titolo = formatta(primo, 'F Y').capitalize()
        inizio, fine = primo, righe[-1][-1]
        if fine.month != primo.month:
            fine = (succ - timedelta(days=1))
    else:
        base = _data(g.get('settimana')) or giorno or oggi
        lun = base - timedelta(days=base.weekday())
        righe = [[lun + timedelta(days=i) for i in range(7)]]
        dentro = lambda d: True  # noqa: E731
        prec, succ = lun - timedelta(days=7), lun + timedelta(days=7)
        param = 'settimana'
        valore = lambda d: d.isoformat()  # noqa: E731
        dom = lun + timedelta(days=6)
        titolo = (f'Sett. {lun.isocalendar()[1]} | {lun.day}' + (f' {formatta(lun, "F")}' if lun.month != dom.month else '')
                  + f' – {dom.day} {formatta(dom, "F")}')
        inizio, fine = lun, dom

    if giorno and inizio <= giorno <= fine:
        scelto = giorno
    else:
        scelto = oggi if inizio <= oggi <= fine else inizio

    # filtri del calendario di tutti: ?via=visita,corso nasconde quei tipi
    nascosti = {t for t in (g.get('via') or '').split(',') if t in FILTRABILI} if tutti else set()

    def link(**cambia):
        q = {'vista': vista, param: valore(inizio), 'giorno': scelto.isoformat()}
        if nascosti:
            q['via'] = ','.join(sorted(nascosti))
        q.update(cambia)
        return '?' + urlencode({k: v for k, v in q.items() if v})

    primo_giorno, ultimo_giorno = righe[0][0], righe[-1][-1]
    per_giorno = eventi(request.user, primo_giorno, ultimo_giorno, tutti=tutti, dip=dip)
    turni = {}
    if dip and not tutti:
        turni = {t.data: t for t in dip.turni.filter(data__range=(primo_giorno, ultimo_giorno), settimana__pubblicata=True)}

    def cella(d):
        tutti_ev = [e for e in per_giorno.get(d, []) if e['tipo'] not in nascosti]
        festa = next((e['titolo'] for e in tutti_ev if e['tipo'] == 'festa'), '')
        ev = [e for e in tutti_ev if e['tipo'] != 'festa']
        return {'data': d, 'fuori': not dentro(d), 'turno': turni.get(d), 'festa': festa,
                'rosso': d.weekday() == 6 or bool(festa), 'eventi': ev[:3], 'altri': max(0, len(ev) - 3),
                'classi': list(dict.fromkeys(e['classe'] for e in ev))[:4], 'n': len(ev),
                'url': link(**{param: valore(inizio), 'giorno': d.isoformat()}) if dentro(d) else
                link(**{'vista': 'mese', 'mese': f'{d:%Y-%m}', 'giorno': d.isoformat()})}

    griglia = [[cella(d) for d in riga] for riga in righe]
    filtri = []
    for t in FILTRABILI if tutti else []:
        if t in ('pulizia', 'manutenzione') and not request.user.is_staff:
            continue
        nome, classe = TIPI[t]
        via = nascosti ^ {t}
        filtri.append({'nome': {'visita': 'Visite', 'corso': 'Corsi', 'scadenza': 'Scadenze', 'riunione': 'Riunioni',
                                'fermo': 'Fermi', 'pulizia': 'Pulizie', 'manutenzione': 'Manutenzioni',
                                'compleanno': 'Compleanni'}[t], 'classe': classe, 'acceso': t not in nascosti,
                       'url': link(via=','.join(sorted(via)) or None)})
    del_giorno = [e for e in per_giorno.get(scelto, []) if e['tipo'] not in nascosti]
    return {
        'kd_vista': vista, 'kd_griglia': griglia, 'kd_titolo': titolo, 'kd_oggi': oggi, 'kd_scelto': scelto,
        'kd_tutti': tutti, 'kd_filtri': filtri, 'kd_del_giorno': del_giorno, 'kd_turno': turni.get(scelto),
        'kd_prec': link(**{param: valore(prec)}), 'kd_succ': link(**{param: valore(succ)}),
        'kd_settimana': link(vista='settimana', mese=None, settimana=scelto.isoformat()),
        'kd_mese': link(vista='mese', settimana=None, mese=f'{scelto:%Y-%m}'),
        'kd_inizio': inizio, 'kd_fine': fine,
        'kd_senza_turni': bool(dip and not tutti and vista == 'settimana' and not turni),
    }


@login_required
def calendario(request):
    """Calendario di tutti: l'ufficio lo apre dalla home, il RI dalla barra in alto del profilo."""
    if not vede_tutti(request.user):
        raise PermissionDenied
    dip = getattr(request.user, 'dipendente', None)
    return render(request, 'turni/calendario.html', {'dip': dip, **contesto(request, dip, tutti=True)})
