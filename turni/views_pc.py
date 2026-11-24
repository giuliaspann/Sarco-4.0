"""Sarco Workspace su PC, Fase 1: il guscio (menu a sinistra, Ctrl K) e la home «Oggi in Sarco».

Disegno scelto da Giulia il 23/11/2026: «A · Plancia di comando». È solo per i dipendenti dell'ufficio
(Giulia, 24/11/2026): gli operai usano l'app del telefono. Tra quelli dell'ufficio, per ora tutti vedono tutto;
ogni numero viene dai dati veri dell'app, e dove un dato non c'è ancora la pagina lo dice.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import format as formatta

from . import richieste as svc
from .models import (AvvisoAssenza, CambioTurno, Annuncio, Fascia, FermoImpianto, Pulizia, RichiestaFerie,
                     RigaProduzione, ProdottoProduzione, RuoloApp, Turno)
from .views_ufficio import _voce

# i quattro riquadri degli impianti: chiave del fermo impianto, nome, postazioni dei turni
IMPIANTI = [
    ('IMP1', 'Impianto 1', ['IMP1']),
    ('IMP2', 'Impianto 2', ['IMP2', 'BARROTTI']),
    ('SABBIA', 'Sabbia', ['SUPERBI', 'SABBIA', 'MULINO']),
    ('METALLI', 'Metalli', ['METALLI']),
]

# il menu: (nome, url o None se l'area arriva più avanti)
MENU_PRINCIPALE = [
    ('Oggi in Sarco', 'turni:pc', 'casa'),
    ('Da approvare', 'turni:pc_richieste', 'spunta'),
    ('Turni', 'turni:pc_turni', 'calendario'),
    ('Pulizie', 'turni:pulizie', 'scopa'),
    ('Manutenzione', 'turni:manutenzione', 'chiave'),
    ('Produzione', 'turni:produzione', 'polso'),
    ('Messaggi', 'turni:messaggi', 'chat'),
]
AREE_IN_ARRIVO = ['Persone', 'Amministrazione', 'Acquisti e vendite', 'Logistica e pesa', 'Qualità e sicurezza',
                  'Sostenibilità', 'Strategia']
INSIEME_IN_ARRIVO = ['Sapere Sarco', 'Idee', 'Grazie']


def _fascia_adesso(adesso):
    """Il turno in corso adesso e il giorno a cui appartiene (la notte dopo mezzanotte è del giorno prima)."""
    ora = adesso.time()
    if time(6) <= ora < time(14):
        return Fascia.MATTINA, adesso.date()
    if time(14) <= ora < time(22):
        return Fascia.POMERIGGIO, adesso.date()
    return Fascia.NOTTE, adesso.date() - timedelta(days=1) if ora < time(6) else adesso.date()


def _tonnellate(**filtro):
    righe = RigaProduzione.objects.filter(prodotto__categoria=ProdottoProduzione.Categoria.PRODOTTO, **filtro)
    return righe.aggregate(t=Sum('tonnellate'))['t'] or Decimal(0)


def _t(numero):
    """328 → «328», 41800 → «41.800» (separatore delle migliaia all'italiana)."""
    return f'{int(round(numero)):,}'.replace(',', '.')


def _linea(valori, larghezza=200, altezza=44):
    """Il piccolo grafico degli ultimi 7 giorni: punti della linea e area sotto, già in coordinate SVG."""
    massimo = max(valori) or 1
    passo = larghezza / (len(valori) - 1)
    punti = [(round(i * passo, 1), round(altezza - 4 - (v / massimo) * (altezza - 10), 1)) for i, v in enumerate(valori)]
    linea = ' '.join(f'{"M" if i == 0 else "L"}{x} {y}' for i, (x, y) in enumerate(punti))
    return {'linea': linea, 'area': f'{linea} L{larghezza} {altezza} L0 {altezza}Z'}


def e_ufficio(utente):
    """Chi può usare la versione PC: mansione «Ufficio» in anagrafica, oppure Direzione / Responsabile turni /
    Amministrazione, oppure gli amministratori dell'app. Gli operai no."""
    if not utente.is_authenticated:
        return False
    if utente.is_superuser or utente.is_staff:
        return True
    dip = getattr(utente, 'dipendente', None)
    return dip is not None and dip.attivo and ('UFFICIO' in dip.mansioni or dip.ruolo_app != RuoloApp.OPERAIO)


def solo_ufficio(vista):
    """Chi non è dell'ufficio torna alla home del telefono."""
    @login_required
    def avvolta(request, *args, **kwargs):
        if not e_ufficio(request.user):
            return redirect('turni:home')
        return vista(request, *args, **kwargs)
    avvolta.__name__, avvolta.__doc__ = vista.__name__, vista.__doc__
    return avvolta


def menu_pc(request):
    """Menu e voci di Ctrl K, uguali in tutte le pagine PC."""
    da_approvare = 0
    if svc.e_responsabile(request.user):
        da_approvare = (CambioTurno.objects.filter(stato=CambioTurno.Stato.ATTESA_UFFICIO).count()
                        + RichiestaFerie.objects.filter(stato=RichiestaFerie.Stato.ATTESA).count()
                        + AvvisoAssenza.objects.filter(esito='', annullato_il__isnull=True).count())
    voci = [{'nome': n, 'url': reverse(u), 'icona': i, 'attiva': request.resolver_match.view_name == u,
             'conta': da_approvare if u == 'turni:pc_richieste' else 0} for n, u, i in MENU_PRINCIPALE]
    return {'menu': voci, 'aree_in_arrivo': AREE_IN_ARRIVO, 'insieme_in_arrivo': INSIEME_IN_ARRIVO}


@solo_ufficio
def oggi(request):
    adesso = timezone.localtime()
    giorno = adesso.date()
    fascia, giorno_turno = _fascia_adesso(adesso)

    # fascia blu: quattro numeri grandi
    t_oggi = {k: _tonnellate(produzione__data=giorno, prodotto__impianto=k) for k in ('IMP1', 'IMP2')}
    t_anno = _tonnellate(produzione__data__year=giorno.year)
    in_turno = (Turno.objects.filter(data=giorno_turno, fascia=fascia).exclude(postazione='UFFICIO')
                .select_related('dipendente'))
    fermi_oggi = list(FermoImpianto.objects.filter(fermo_dal__date=giorno))
    numeri = {
        't_oggi': _t(sum(t_oggi.values())), 't_imp1': _t(t_oggi['IMP1']), 't_imp2': _t(t_oggi['IMP2']),
        'c_produzione': any(t_oggi.values()),
        't_anno': _t(t_anno), 'c_anno': bool(t_anno),
        'in_turno': in_turno.count(),
        'fermi': len(fermi_oggi), 'fermi_minuti': sum(f.minuti for f in fermi_oggi),
    }

    # quattro riquadri impianti
    ultimi7 = [giorno - timedelta(days=6 - i) for i in range(7)]
    impianti = []
    for chiave, nome, postazioni in IMPIANTI:
        fermo = FermoImpianto.objects.filter(impianto=chiave, ripartito_il__isnull=True).first()
        ripartito = next((f for f in fermi_oggi if f.impianto == chiave and not f.in_corso), None)
        persone = [t for t in in_turno if t.postazione in postazioni]
        ct = next((t.dipendente.nome_breve for t in persone if t.capoturno or t.ruolo == 'CT'), None)
        if fermo:
            stato, tono = f'Fermo da {fermo.durata}', 'rosso'
            riga = f'{fermo.get_causa_display()}' + (f' · {fermo.macchina}' if fermo.macchina_id else '')
        elif ripartito:
            stato, tono = f'Ripartito {timezone.localtime(ripartito.ripartito_il):%H:%M}', 'arancio'
            riga = f'Fermo {ripartito.durata} · {ripartito.get_causa_display().lower()}'
        elif persone:
            stato, tono = 'In turno', 'verde'
            riga = f'{len(persone)} {"persona" if len(persone) == 1 else "persone"}' + (f' · CT {ct}' if ct else '')
        else:
            stato, tono, riga = 'Nessuno in turno', 'grigio', 'Da programma turni'
        grafico = None
        if chiave in ('IMP1', 'IMP2'):
            valori = [float(_tonnellate(produzione__data=g, prodotto__impianto=chiave)) for g in ultimi7]
            if any(valori):
                grafico = _linea(valori)
            riga += f' · {_t(t_oggi[chiave])} t oggi' if t_oggi[chiave] else ''
        impianti.append({'nome': nome, 'stato': stato, 'tono': tono, 'riga': riga, 'grafico': grafico,
                         'url': reverse('turni:fermi')})

    # «Da fare in ufficio»: le richieste vere da approvare + le pulizie da verificare
    responsabile = svc.e_responsabile(request.user)
    aperte = [_voce('cambio', c) for c in CambioTurno.objects.filter(stato=CambioTurno.Stato.ATTESA_UFFICIO).select_related('richiedente', 'collega')]
    aperte += [_voce('ferie', f) for f in RichiestaFerie.objects.filter(stato=RichiestaFerie.Stato.ATTESA).select_related('dipendente')]
    aperte += [_voce('avviso', a) for a in AvvisoAssenza.objects.filter(esito='', annullato_il__isnull=True).select_related('dipendente')]
    aperte.sort(key=lambda v: v['quando'])
    sigle = {'cambio': 'TU', 'ferie': 'PE', 'avviso': 'AV'}
    da_fare = [{'sigla': sigle[v['tipo']], 'titolo': f'{v["cosa"]}', 'sotto': f'{v["chi"]} · {formatta(timezone.localtime(v["quando"]), "j/m H:i")}',
                'url': f"{reverse('turni:pc_richieste')}?tipo={v['tipo']}&pk={v['pk']}",
                'tipo': v['tipo'], 'pk': v['pk'], 'decide': responsabile}
               for v in aperte]
    da_verificare = Pulizia.objects.filter(stato=Pulizia.Stato.FATTA, turno__data__gte=giorno - timedelta(days=2)).count()
    if da_verificare:
        da_fare.append({'sigla': 'PU', 'titolo': f'{da_verificare} {"pulizia fatta" if da_verificare == 1 else "pulizie fatte"} da verificare',
                        'sotto': 'Pulizie · con foto prima e dopo', 'url': reverse('turni:pulizie'), 'decide': False})

    # colonna destra: Bacheca e avanzamento pulizie del turno in corso per area
    bacheca = list(Annuncio.objects.all()[:2])
    pulizie = Pulizia.objects.filter(turno__data=giorno_turno, turno__fascia=fascia).select_related('turno')
    per_area = {}
    for p in pulizie:
        area = p.turno.get_postazione_display() or 'Altro'
        fatte, tot = per_area.get(area, (0, 0))
        per_area[area] = (fatte + (p.stato in (Pulizia.Stato.FATTA, Pulizia.Stato.VERIFICATA)), tot + 1)
    avanzamento = sorted(({'area': a, 'fatte': f, 'tot': t, 'pct': round(100 * f / t)} for a, (f, t) in per_area.items()),
                         key=lambda r: -r['tot'])[:5]

    nome = request.user.first_name or request.user.username
    saluto = 'Buongiorno' if adesso.hour < 13 else 'Buon pomeriggio' if adesso.hour < 18 else 'Buonasera'
    contesto = {
        'titolo_pagina': 'Oggi in Sarco',
        'giorno': formatta(giorno, 'l j F').capitalize(), 'turno_ora': dict(Fascia.choices)[fascia],
        'saluto': f'{saluto}, {nome.split()[0].capitalize()}',
        'numeri': numeri, 'impianti': impianti, 'da_fare': da_fare[:5], 'da_fare_tot': len(da_fare),
        'bacheca': bacheca, 'avanzamento': avanzamento, 'fascia_nome': dict(Fascia.choices)[fascia],
    }
    contesto.update(menu_pc(request))
    return render(request, 'turni/pc/oggi.html', contesto)


# ---------------------------------------------------------------- Da approvare (proposta B scelta da Giulia il 24/11/2026)

SIGLE_TIPO = {'cambio': ('TU', 'blu'), 'ferie': ('PE', 'verde'), 'MALATTIA': ('MA', 'rosso'), 'RITARDO': ('RI', 'arancio'),
              'USCITA': ('US', 'arancio')}


def _riga_elenco(tipo, o):
    v = _voce(tipo, o)
    sigla, tono = SIGLE_TIPO.get(tipo if tipo != 'avviso' else o.tipo, ('AV', 'arancio'))
    quando = timezone.localtime(v['quando'])
    v.update({'sigla': sigla, 'tono': tono,
              'ora': f'{quando:%H:%M}' if quando.date() == timezone.localdate() else formatta(quando, 'j/m')})
    return v


def _dettaglio(tipo, o):
    """Cosa serve per decidere: i giorni prima → dopo del cambio, i turni che salta, chi manca già."""
    from .views_richieste import _righe_cambio

    d = {'motivo': '', 'persone': [], 'turni': [], 'colleghi_assenti': [], 'etichetta_turni': 'Turni che salta'}
    if tipo == 'cambio':
        d['motivo'] = o.motivo
        d['persone'] = [(p, _righe_cambio(o, p)) for p in (o.richiedente, o.collega)]
    elif tipo == 'ferie':
        d['motivo'] = o.motivo
        d['turni'] = [t for t in o.dipendente.turni.filter(data__range=(o.dal, o.al)) if t.lavora]
        d['colleghi_assenti'] = [f.dipendente.nome_breve for f in RichiestaFerie.objects.filter(
            stato=RichiestaFerie.Stato.APPROVATA, dal__lte=o.al, al__gte=o.dal).exclude(dipendente=o.dipendente).select_related('dipendente')]
    else:
        d['motivo'] = o.nota
        if o.tipo != 'MALATTIA':  # ritardo e uscita non saltano il turno
            d['etichetta_turni'] = 'Turno di quel giorno'
        d['turni'] = [t for t in o.dipendente.turni.filter(data=o.data) if t.lavora]
        d['colleghi_assenti'] = [a.dipendente.nome_breve for a in AvvisoAssenza.objects.filter(
            data=o.data, annullato_il__isnull=True).exclude(esito='rifiutato').exclude(pk=o.pk).select_related('dipendente')]
    return d


@solo_ufficio
def richieste(request):
    from django.contrib import messages
    from django.core.exceptions import PermissionDenied
    from .views_ufficio import _oggetto, decidi

    responsabile = svc.e_responsabile(request.user)
    if request.method == 'POST':
        if not responsabile:
            raise PermissionDenied
        tipo, scelta = request.POST.get('tipo'), request.POST.get('scelta')
        o = _oggetto(tipo, request.POST.get('pk'))
        if scelta not in ('approva', 'rifiuta'):
            messages.error(request, 'Scegli Approva o Rifiuta.')
        elif not _voce(tipo, o)['aperta']:
            messages.info(request, 'Questa richiesta è già stata decisa.')
        else:
            decidi(request, tipo, o, scelta == 'approva', request.POST.get('nota'))
        return redirect('turni:pc' if request.POST.get('torna') == 'plancia' else 'turni:pc_richieste')

    decise = request.GET.get('vista') == 'decise'
    if decise:
        oggetti = [('cambio', c) for c in CambioTurno.objects.exclude(stato__in=CambioTurno.IN_CORSO).select_related('richiedente', 'collega')[:30]]
        oggetti += [('ferie', f) for f in RichiestaFerie.objects.exclude(stato=RichiestaFerie.Stato.ATTESA).select_related('dipendente')[:30]]
        oggetti += [('avviso', a) for a in AvvisoAssenza.objects.exclude(esito='', annullato_il__isnull=True).select_related('dipendente')[:30]]
    else:
        oggetti = [('cambio', c) for c in CambioTurno.objects.filter(stato=CambioTurno.Stato.ATTESA_UFFICIO).select_related('richiedente', 'collega')]
        oggetti += [('ferie', f) for f in RichiestaFerie.objects.filter(stato=RichiestaFerie.Stato.ATTESA).select_related('dipendente')]
        oggetti += [('avviso', a) for a in AvvisoAssenza.objects.filter(esito='', annullato_il__isnull=True).select_related('dipendente')]
    elenco = sorted((dict(_riga_elenco(t, o), oggetto=o) for t, o in oggetti), key=lambda v: v['quando'], reverse=decise)[:40]

    scelta = None
    if request.GET.get('tipo') and request.GET.get('pk'):
        tipo = request.GET['tipo']
        o = _oggetto(tipo, request.GET['pk'])
        scelta = dict(_riga_elenco(tipo, o), oggetto=o)
    elif elenco:
        scelta = elenco[0]
    if scelta:
        scelta['dettaglio'] = _dettaglio(scelta['tipo'], scelta['oggetto'])
        for v in elenco:
            v['scelta'] = v['tipo'] == scelta['tipo'] and v['pk'] == scelta['pk']

    contesto = {'titolo_pagina': 'Da approvare', 'elenco': elenco, 'v': scelta, 'decise': decise,
                'responsabile': responsabile}
    contesto.update(menu_pc(request))
    return render(request, 'turni/pc/richieste.html', contesto)


# ---------------------------------------------------------------- Turni (proposta B scelta da Giulia il 24/11/2026)

@solo_ufficio
def turni(request):
    """Il Layout Turni a tutta larghezza (Per area) o la griglia Per dipendente; a destra il pannello dell'ufficio:
    carica turni, turni extra aperti, turni cambiati con la presa visione dei dipendenti."""
    from .models import ModificaTurno, Settimana, TurnoExtra
    from .views import griglia_turni, leggi_data

    oggi = timezone.localdate()
    g = griglia_turni(leggi_data(request.GET.get('settimana'), oggi))
    vista = 'dipendente' if request.GET.get('vista') == 'dipendente' else 'area'
    q = (request.GET.get('q') or '').strip()
    if q:
        g['righe'] = [r for r in g['righe'] if q.lower() in r['nome'].lower()]
    extra = list(TurnoExtra.objects.filter(data__gte=oggi, chiusa=False).prefetch_related('disponibilita__dipendente'))
    modifiche = list(ModificaTurno.objects.filter(creata_il__gte=timezone.now() - timedelta(days=14))
                     .select_related('dipendente').order_by('vista_il', '-creata_il')[:12])
    ultima = Settimana.objects.filter(pubblicata=True).select_related('caricata_da').order_by('-lunedi').first()
    contesto = dict(g, titolo_pagina='Turni', vista=vista, q=q, extra=extra, modifiche=modifiche,
                    da_vedere=sum(1 for m in modifiche if not m.vista_il), ultima=ultima,
                    puo_caricare=request.user.is_staff or svc.e_responsabile(request.user),
                    fine=g['lunedi'] + timedelta(days=6), oggi_iso=oggi.isoformat())
    contesto.update(menu_pc(request))
    return render(request, 'turni/pc/turni.html', contesto)
