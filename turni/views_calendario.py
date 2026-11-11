"""Calendario dell'ufficio (Giulia, 11/11/2026): in un solo posto riunioni, fermi impianto programmati,
pulizie programmate, manutenzioni programmate e scadenze del personale (visite mediche, corsi, patentini)."""

import calendar
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import format as formatta

from .models import Comunicazione, Intervento, Pulizia, Riunione, Scadenza
from .views_riunioni import puo_programmare_riunione

# tipo: (nome, classe del colore)
TIPI = {
    'riunione': ('Riunione', 'cal-blu'),
    'fermo': ('Fermo impianto', 'cal-rosso'),
    'pulizia': ('Pulizia', 'cal-verde'),
    'manutenzione': ('Manutenzione', 'cal-arancio'),
    'scadenza': ('Scadenza', 'cal-viola'),
}


def puo_vedere(utente):
    return puo_programmare_riunione(utente)


def _evento(tipo, giorno, titolo, sotto, url, ora=''):
    nome, classe = TIPI[tipo]
    return {'tipo': tipo, 'nome_tipo': nome, 'classe': classe, 'giorno': giorno, 'titolo': titolo, 'sotto': sotto,
            'url': url, 'ora': ora}


def eventi(utente, dal, al):
    """{giorno: [eventi]} tra dal e al compresi."""
    per_giorno = {}

    def metti(e):
        if dal <= e['giorno'] <= al:
            per_giorno.setdefault(e['giorno'], []).append(e)

    for r in Riunione.objects.filter(annullata=False, inizio__date__range=(dal, al)):
        i, f = timezone.localtime(r.inizio), timezone.localtime(r.fine)
        metti(_evento('riunione', i.date(), r.titolo, f'{i:%H:%M}–{f:%H:%M} · {r.luogo}',
                      reverse('turni:riunione', args=[r.pk]), f'{i:%H:%M}'))

    for c in Comunicazione.objects.filter(tipo=Comunicazione.Tipo.FERMO, dal__isnull=False, dal__date__lte=al).exclude(
            al__date__lt=dal):
        inizio, fine = timezone.localtime(c.dal), timezone.localtime(c.al or c.dal)
        dove = c.get_luogo_display() if c.luogo else 'Impianto'
        motivo = f' · {c.get_motivo_display().lower()}' if c.motivo else ''
        g = inizio.date()
        while g <= fine.date():
            metti(_evento('fermo', g, f'{dove} fermo{motivo}', f'{inizio:%H:%M}–{fine:%H:%M} · {c.testo[:80]}',
                          reverse('turni:comunicazione', args=[c.pk]), f'{inizio:%H:%M}' if g == inizio.date() else ''))
            g += timedelta(days=1)

    for p in Pulizia.objects.filter(richiesta_da__isnull=False, turno__data__range=(dal, al)).select_related(
            'turno__dipendente', 'elemento'):
        metti(_evento('pulizia', p.turno.data, p.titolo, f'{p.turno.descrizione_fascia} · {p.turno.dipendente.nome_breve}'
                      f' · {p.get_stato_display().lower()}', reverse('turni:capoturno') + f'?giorno={p.turno.data.isoformat()}'))

    for i in Intervento.objects.filter(tipo=Intervento.Tipo.PROGRAMMATA, da_fare_il__range=(dal, al)).exclude(
            stato=Intervento.Stato.RIFIUTATA).select_related('macchina'):
        metti(_evento('manutenzione', i.da_fare_il, i.macchina.nome, f'{i.descrizione[:80]} · {i.get_stato_display().lower()}',
                      reverse('turni:intervento', args=[i.pk])))

    if utente.is_staff:  # le scadenze del personale le vede l'ufficio
        for s in Scadenza.objects.filter(chiusa_il__isnull=True, dipendente__attivo=True, scade_il__range=(dal, al)).select_related(
                'dipendente'):
            metti(_evento('scadenza', s.scade_il, f'{s.get_tipo_display()} · {s.dipendente.nome_breve}', s.descrizione or 'scadenza',
                          reverse('turni:scadenze') + f'?q={s.dipendente.nome}'))

    for lista in per_giorno.values():
        lista.sort(key=lambda e: (e['ora'] or '99', e['tipo']))
    return per_giorno


def eventi_prossimi(utente, giorni):
    """Quanti eventi nei prossimi giorni (per il numerino sulla home)."""
    if not puo_vedere(utente):
        return 0
    oggi = timezone.localdate()
    return sum(len(v) for v in eventi(utente, oggi, oggi + timedelta(days=giorni - 1)).values())


@login_required
def calendario(request):
    if not puo_vedere(request.user):
        raise PermissionDenied
    oggi = timezone.localdate()
    try:
        anno, mese = (int(x) for x in (request.GET.get('mese') or '').split('-'))
        primo = date(anno, mese, 1)
    except (ValueError, TypeError):
        primo = oggi.replace(day=1)
    try:
        scelto = date.fromisoformat(request.GET.get('giorno') or '')
    except ValueError:
        scelto = None
    if not scelto or (scelto.year, scelto.month) != (primo.year, primo.month):
        scelto = oggi if (oggi.year, oggi.month) == (primo.year, primo.month) else primo

    settimane = calendar.Calendar(firstweekday=0).monthdatescalendar(primo.year, primo.month)
    per_giorno = eventi(request.user, settimane[0][0], settimane[-1][-1])
    griglia = [[{'data': g, 'fuori': g.month != primo.month,
                 'classi': list(dict.fromkeys(e['classe'] for e in per_giorno.get(g, [])))[:4],
                 'n': len(per_giorno.get(g, []))} for g in sett] for sett in settimane]
    prec = (primo - timedelta(days=1)).replace(day=1)
    succ = (primo + timedelta(days=32)).replace(day=1)
    return render(request, 'turni/calendario.html', {
        'griglia': griglia, 'primo': primo, 'nome_mese': formatta(primo, 'F Y').capitalize(),
        'prec': f'{prec:%Y-%m}', 'succ': f'{succ:%Y-%m}', 'mese': f'{primo:%Y-%m}',
        'oggi': oggi, 'scelto': scelto, 'del_giorno': per_giorno.get(scelto, []),
        'tipi': [(k, n, c) for k, (n, c) in TIPI.items() if k != 'scadenza' or request.user.is_staff],
    })
