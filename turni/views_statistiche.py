"""Statistiche: produzione di fine turno e analisi del prodotto, inserite con tasti e foto, e report a richiesta.

Prima questi dati giravano come foto nei gruppi WhatsApp: qui restano in ordine e si possono sommare.
"""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import lettura
from . import manutenzione as mn
from .models import INQUINANTI, AnalisiProdotto, ProdottoProduzione, ProduzioneTurno
from .views_produzione import percentuali, puo_vedere, turno_corrente

PERIODI = [('7', 'Ultimi 7 giorni'), ('30', 'Ultimi 30 giorni'), ('90', 'Ultimi 3 mesi')]


def _serve(request):
    if not puo_vedere(request.user):
        raise PermissionDenied


def _numero(testo, intero=False):
    testo = (testo or '').strip().replace(',', '.')
    if not testo:
        return None
    try:
        v = Decimal(testo)
    except InvalidOperation:
        raise ValueError
    if v < 0 or v > 1000000:
        raise ValueError
    return int(v) if intero else v


@login_required
def statistiche(request):
    _serve(request)
    oggi = timezone.localdate()
    produzioni = list(ProduzioneTurno.objects.filter(data__gte=oggi - timedelta(days=6)).prefetch_related('righe__prodotto')[:6])
    for t in produzioni:
        t.totale = sum(r.tonnellate for r in t.righe.all())
    return render(request, 'turni/stat_home.html', {
        'produzioni': produzioni,
        'analisi': AnalisiProdotto.objects.filter(data__gte=oggi - timedelta(days=6))[:8],
        'periodi': PERIODI,
    })


def avvisa_fuori_limite(a, utente):
    """Analisi fuori specifica: avviso al responsabile e, per tutti, un avviso importante in bacheca."""
    from . import push
    from .models import Annuncio
    from .views_messaggi import destinatari

    fuori = a.fuori_limite
    if not fuori:
        return
    testo = ', '.join(f"{v['nome']} {v['gt']:.0f} g/t (limite {v['limite']})" for v in fuori)
    mn.avvisa(mn.responsabili(), utente, f'🧪 Fuori limite · {a}', testo, reverse('turni:analisi', args=[a.pk]))
    turno = f' · {a.get_fascia_display()}' if a.fascia else ''
    avviso = Annuncio.objects.create(
        testo=f'🧪 Analisi fuori specifica: {a.get_campione_display()} del {a.data:%d/%m}{turno}' + (f' (#{a.numero})' if a.numero else '')
        + f'. {testo}.', importante=True, autore=utente)
    push.invia(destinatari(utente), 'Avviso importante', avviso.testo, reverse('turni:messaggi') + '?vista=bacheca')


@login_required
def analisi_nuova(request):
    _serve(request)
    if request.method == 'POST':
        try:
            giorno = date.fromisoformat(request.POST.get('data') or '')
        except ValueError:
            giorno = None
        campione = request.POST.get('campione')
        try:
            valori = {c: _numero(request.POST.get(c)) for c, _, _ in INQUINANTI}
            peso = _numero(request.POST.get('peso_kg'))
            numero = _numero(request.POST.get('numero'), intero=True)
        except ValueError:
            messages.error(request, 'Uno dei numeri non è valido.')
        else:
            if not giorno or campione not in AnalisiProdotto.Campione.values:
                messages.error(request, 'Scegli il campione e il giorno.')
            elif all(v is None for v in valori.values()):
                messages.error(request, 'Scrivi almeno un valore (o leggilo dalla foto).')
            else:
                fascia = request.POST.get('fascia') if request.POST.get('fascia') in ('1T', '2T', 'N') else ''
                a = AnalisiProdotto(data=giorno, fascia=fascia, campione=campione, peso_kg=peso, numero=numero,
                                    note=(request.POST.get('note') or '').strip()[:500], inserita_da=request.user, **valori)
                if request.FILES.get('foto'):
                    try:
                        a.foto.save('analisi.jpg', mn.comprimi_foto(request.FILES['foto']), save=False)
                    except (ValueError, OSError):
                        messages.error(request, 'La foto non è valida: analisi salvata senza foto.')
                a.save()
                avvisa_fuori_limite(a, request.user)
                messages.success(request, 'Analisi salvata.')
                return redirect('turni:analisi', a.pk)
    giorno, fascia = turno_corrente()
    return render(request, 'turni/analisi_nuova.html', {
        'campioni': AnalisiProdotto.Campione.choices,
        'inquinanti': [(c, n, l, request.POST.get(c, '')) for c, n, l in INQUINANTI], 'giorno': giorno, 'fascia': fascia,
        'fasce': ProduzioneTurno.FASCE, 'dati': request.POST, 'leggi_foto': lettura.attiva(),
    })


@login_required
def analisi(request, analisi_id):
    _serve(request)
    a = get_object_or_404(AnalisiProdotto, pk=analisi_id)
    if request.method == 'POST' and request.POST.get('azione') == 'elimina' and (mn.e_resp(request.user) or a.inserita_da_id == request.user.pk):
        a.delete()
        messages.success(request, 'Analisi eliminata.')
        return redirect('turni:statistiche')
    return render(request, 'turni/analisi.html', {'a': a})


@login_required
def foto_analisi(request, analisi_id):
    _serve(request)
    a = get_object_or_404(AnalisiProdotto, pk=analisi_id)
    if not a.foto:
        raise Http404
    return FileResponse(a.foto.open('rb'), content_type='image/jpeg')


@login_required
@require_POST
def leggi_foto(request):
    """Riceve la foto dal modulo e restituisce i valori letti, da controllare prima di salvare."""
    _serve(request)
    if not lettura.attiva():
        return JsonResponse({'errore': 'Lettura automatica non attiva.'}, status=503)
    foto = request.FILES.get('foto')
    if not foto:
        return JsonResponse({'errore': 'Prima scatta o scegli la foto.'}, status=400)
    try:
        jpeg = mn.comprimi_foto(foto).read()
    except (ValueError, OSError):
        return JsonResponse({'errore': 'La foto non è valida.'}, status=400)
    try:
        if request.POST.get('tipo') == 'produzione':
            valori = lettura.leggi_produzione(jpeg, list(ProdottoProduzione.objects.filter(attivo=True)))
            campi = {f'p{pk}': str(v).replace('.', ',') for pk, v in valori.items()}
        else:
            campi = {k: (v if k == 'campione' else str(v).replace('.', ',')) for k, v in lettura.leggi_analisi(jpeg).items()}
    except lettura.LetturaNonRiuscita as e:
        return JsonResponse({'errore': str(e)}, status=502)
    if not campi:
        return JsonResponse({'errore': 'Nella foto non trovo numeri: scrivili a mano.'}, status=422)
    return JsonResponse({'campi': campi})


# ---------------------------------------------------------------- report


def dati_report(giorni):
    oggi = timezone.localdate()
    dal = oggi - timedelta(days=giorni - 1)
    produzioni = list(ProduzioneTurno.objects.filter(data__range=(dal, oggi)).prefetch_related('righe__prodotto'))
    totali, perc = {}, {}
    for t in produzioni:
        for pid, p in percentuali(t).items():
            if p is not None:
                perc.setdefault(pid, []).append(p)
        for r in t.righe.all():
            totali[r.prodotto] = totali.get(r.prodotto, 0) + r.tonnellate
    prodotti = []
    for p in sorted(totali, key=lambda p: (p.impianto, p.ordine)):
        valori = perc.get(p.pk, [])
        prodotti.append({'p': p, 'tonnellate': totali[p], 'perc': sum(valori) / len(valori) if valori else None})
    impianti = {}
    for x in prodotti:
        impianti[x['p'].get_impianto_display()] = impianti.get(x['p'].get_impianto_display(), 0) + x['tonnellate']

    analisi = list(AnalisiProdotto.objects.filter(data__range=(dal, oggi)))
    per_campione = {}
    for a in analisi:
        per_campione.setdefault(a.get_campione_display(), []).append(a)
    campioni = []
    for nome, elenco in sorted(per_campione.items()):
        medie_gt = []
        for campo, inq, limite in INQUINANTI:
            vals = [v['gt'] for a in elenco for v in a.valori() if v['campo'] == campo and v['gt'] is not None]
            if vals:
                m = sum(vals) / len(vals)
                medie_gt.append({'nome': inq, 'media': m, 'limite': limite, 'fuori': m > limite,
                                 'volte_fuori': sum(1 for v in vals if v > limite), 'n': len(vals)})
        campioni.append({'nome': nome, 'n': len(elenco), 'medie': medie_gt})
    return {
        'dal': dal, 'al': oggi, 'turni': len(produzioni), 'prodotti': prodotti, 'impianti': impianti,
        'campioni': campioni, 'n_analisi': len(analisi), 'fuori': [a for a in analisi if a.fuori_limite],
    }


def testo_report(d):
    """Lo stesso report in testo semplice, da incollare su WhatsApp."""
    righe = [f"📊 REPORT {d['dal']:%d/%m} – {d['al']:%d/%m}", '']
    if d['prodotti']:
        righe.append(f"PRODUZIONE ({d['turni']} turni)")
        for imp, t in d['impianti'].items():
            righe.append(f'{imp}: {t:.1f} t')
        for x in d['prodotti']:
            p = f" ({x['perc']:.1f}%)" if x['perc'] is not None else ''
            righe.append(f"  {x['p'].codice} {x['p'].nome}: {x['tonnellate']:.1f} t{p}")
        righe.append('')
    if d['campioni']:
        righe.append(f"ANALISI ({d['n_analisi']})")
        for c in d['campioni']:
            righe.append(f"{c['nome']} · {c['n']} analisi")
            for m in c['medie']:
                righe.append(f"  {m['nome']}: {m['media']:.0f} g/t (limite {m['limite']}){' ⚠️' if m['fuori'] else ''}")
    return '\n'.join(righe).strip()


@login_required
def report(request):
    _serve(request)
    giorni = request.GET.get('giorni') if request.GET.get('giorni') in dict(PERIODI) else '7'
    d = dati_report(int(giorni))
    return render(request, 'turni/stat_report.html', {**d, 'periodi': PERIODI, 'giorni': giorni, 'testo': testo_report(d)})
