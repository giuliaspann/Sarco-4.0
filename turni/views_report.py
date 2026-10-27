"""Report assenze per la direzione e storico personale delle assenze (ritardi, malattie, uscite, ferie, permessi)."""

from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from . import saldi
from .models import FASCE_LAVORATIVE, AvvisoAssenza, Dipendente, Disponibilita, Fascia, Postazione, RichiestaFerie, Turno
from .views import ORDINE_GRUPPI, dipendente_di, leggi_data
from .views_messaggi import e_direzione


def vede_report(utente):
    return utente.is_staff or e_direzione(utente)


def periodi(oggi):
    inizio_mese = oggi.replace(day=1)
    fine_scorso = inizio_mese - timedelta(days=1)
    lunedi = oggi - timedelta(days=oggi.weekday())
    return [
        ('mese', 'Questo mese', inizio_mese, (inizio_mese + timedelta(days=32)).replace(day=1) - timedelta(days=1)),
        ('scorso', 'Mese scorso', fine_scorso.replace(day=1), fine_scorso),
        ('prossime', 'Prossime 2 settimane', lunedi, lunedi + timedelta(days=13)),
    ]


def _giorni_di(r, dal, al):
    """Le giornate di una richiesta che cadono nel periodo (le richieste a ore valgono 0 giorni)."""
    if r.a_ore:
        return 0
    return max(0, (min(r.al, al) - max(r.dal, dal)).days + 1)


@login_required
def report_assenze(request):
    if not vede_report(request.user):
        raise PermissionDenied
    oggi = timezone.localdate()
    scelte = periodi(oggi)
    chiave = request.GET.get('periodo', 'prossime')
    _, nome, dal, al = next((p for p in scelte if p[0] == chiave), scelte[2])

    turni = Turno.objects.filter(data__range=(dal, al), dipendente__attivo=True).select_related('dipendente')
    previsti = Counter()  # giornate in cui la persona era attesa al lavoro (o in ferie/permesso)
    per_impianto = defaultdict(lambda: {'previsti': 0, 'assenze': 0})
    impianto_di = {}
    notti = Counter()
    for t in turni:
        if t.fascia in FASCE_LAVORATIVE or t.fascia in (Fascia.FERIE, Fascia.PERMESSO):
            previsti[t.dipendente] += 1
        if t.postazione:
            impianto_di.setdefault(t.dipendente, Counter())[t.postazione] += 1
        if t.fascia == Fascia.NOTTE:
            notti[t.dipendente] += 1

    righe = defaultdict(lambda: {'malattia': 0, 'ritardi': 0, 'uscite': 0, 'altro': 0, 'ferie': 0, 'permessi_ore': Decimal('0')})
    for a in AvvisoAssenza.objects.filter(data__range=(dal, al), dipendente__attivo=True).select_related('dipendente'):
        chiave_tipo = {'MALATTIA': 'malattia', 'RITARDO': 'ritardi', 'USCITA': 'uscite'}.get(a.tipo, 'altro')
        righe[a.dipendente][chiave_tipo] += 1
    for r in RichiestaFerie.objects.filter(stato=RichiestaFerie.Stato.APPROVATA, dal__lte=al, al__gte=dal,
                                           dipendente__attivo=True).select_related('dipendente'):
        if r.tipo == RichiestaFerie.Tipo.FERIE:
            righe[r.dipendente]['ferie'] += _giorni_di(r, dal, al)
        else:
            r.dal, r.al = max(r.dal, dal), min(r.al, al)
            righe[r.dipendente]['permessi_ore'] += saldi.ore_richiesta(r)

    persone = []
    for dip, v in righe.items():
        v['dip'] = dip
        v['voci'] = [t for t in (
            v['malattia'] and f"🤒 {v['malattia']} malattia",
            v['ritardi'] and f"⏰ {v['ritardi']} ritard{'o' if v['ritardi'] == 1 else 'i'}",
            v['uscite'] and f"🚪 {v['uscite']} uscit{'a' if v['uscite'] == 1 else 'e'}",
            v['altro'] and f"📝 {v['altro']} altro",
            v['ferie'] and f"🏖️ {v['ferie']} gg ferie",
            v['permessi_ore'] and f"⏸️ {v['permessi_ore']:g} h permesso".replace('.', ','),
        ) if t]
        v['assenze'] = v['malattia'] + v['ferie'] + v['permessi_ore'] / saldi.ORE_GIORNO
        persone.append(v)
        imp = impianto_di.get(dip)
        if imp:
            per_impianto[imp.most_common(1)[0][0]]['assenze'] += v['assenze']
    for dip, n in previsti.items():
        imp = impianto_di.get(dip)
        if imp:
            per_impianto[imp.most_common(1)[0][0]]['previsti'] += n
    persone.sort(key=lambda v: (-(v['malattia'] + v['ritardi'] + v['uscite'] + v['altro']), -v['assenze'], v['dip'].nome))

    nomi = dict(Postazione.choices)
    impianti = [
        {'nome': nomi[p], 'previsti': per_impianto[p]['previsti'], 'assenze': per_impianto[p]['assenze'],
         'tasso': per_impianto[p]['assenze'] * 100 / per_impianto[p]['previsti'] if per_impianto[p]['previsti'] else 0}
        for p in ORDINE_GRUPPI if per_impianto[p]['previsti']
    ]
    tot_previsti = sum(previsti.values())
    tot_assenze = sum((v['assenze'] for v in persone), Decimal('0'))
    totali = {k: sum(v[k] for v in persone) for k in ('malattia', 'ritardi', 'uscite', 'altro', 'ferie', 'permessi_ore')}
    residui = saldi.tutti()
    return render(request, 'turni/report_assenze.html', {
        'scelte': scelte, 'chiave': chiave, 'nome_periodo': nome, 'dal': dal, 'al': al,
        'totali': totali, 'tot_previsti': tot_previsti,
        'tasso': tot_assenze * 100 / tot_previsti if tot_previsti else 0,
        'persone': persone, 'impianti': impianti,
        'residui': residui, 'soglia': saldi.SOGLIA_FERIE,
        'accumulate': [r for r in residui if r['ferie'] > saldi.SOGLIA_FERIE],
        'tot_ferie': sum((r['ferie'] for r in residui), Decimal('0')),
        'tot_rol': sum((r['rol'] for r in residui), Decimal('0')),
        'notti': notti.most_common(8), 'tot_notti': sum(notti.values()),
        'extra': Disponibilita.objects.filter(confermata=True, extra__data__range=(dal, al)).count(),
    })


@login_required
def storico_assenze(request):
    """Le mie assenze: ogni ritardo, malattia, uscita anticipata, ferie e permesso, per anno.
    La direzione può aprire quello di chiunque (?dip=)."""
    if request.GET.get('dip') and vede_report(request.user):
        dip = get_object_or_404(Dipendente, pk=request.GET['dip'])
    else:
        dip = dipendente_di(request)
        if dip is None:
            return render(request, 'turni/nessun_dipendente.html')
    oggi = timezone.localdate()
    anno = int(request.GET.get('anno') or oggi.year)
    voci = []
    for a in dip.avvisi.filter(data__year=anno):
        voci.append({'data': a.data, 'icona': {'MALATTIA': '🤒', 'RITARDO': '⏰', 'USCITA': '🚪'}.get(a.tipo, '📝'),
                     'titolo': a.get_tipo_display() + (f' · {a.orario}' if a.orario else ''), 'nota': a.nota, 'tipo': a.tipo})
    for r in dip.richieste_ferie.filter(stato=RichiestaFerie.Stato.APPROVATA, dal__year=anno):
        quanto = r.orario if r.a_ore else f'{r.giorni} giorn{"o" if r.giorni == 1 else "i"}'
        periodo = '' if r.a_ore or r.giorni == 1 else f'fino al {r.al:%d/%m}'
        voci.append({'data': r.dal, 'icona': '🏖️' if r.tipo == RichiestaFerie.Tipo.FERIE else '⏸️',
                     'titolo': f'{r.get_tipo_display()} · {quanto}', 'nota': periodo, 'tipo': r.tipo})
    voci.sort(key=lambda v: v['data'], reverse=True)
    conta = Counter(v['tipo'] for v in voci)
    riquadri = [('🤒', 'Malattia', conta['MALATTIA']), ('⏰', 'Ritardi', conta['RITARDO']),
                ('🚪', 'Uscite anticipate', conta['USCITA']), ('📝', 'Altro', conta['ALTRO'])]
    return render(request, 'turni/storico_assenze.html', {
        'dip': dip, 'mio': dip == dipendente_di(request), 'anno': anno, 'anni': [oggi.year, oggi.year - 1],
        'voci': voci, 'riquadri': riquadri, 'saldo': saldi.residuo(dip),
    })
