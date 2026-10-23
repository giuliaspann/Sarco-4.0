"""Produzione di fine turno: le tonnellate lette sul display della pesa e le percentuali di scarto.

Le percentuali sono sul totale dell'impianto nel turno; si confrontano con la media degli ultimi 30 giorni
(es. "scarto barrotti 14% nel 2° turno, la media è attorno al 6%").
"""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from . import manutenzione as mn
from .models import ProdottoProduzione, ProduzioneTurno, RigaProduzione

# oltre questo multiplo della media, lo scarto viene segnalato al responsabile
SOGLIA = Decimal('1.5')


def puo_vedere(utente):
    """Per ora tutti i dipendenti (prima questi dati giravano nei gruppi WhatsApp) e l'ufficio."""
    return utente.is_authenticated and (utente.is_staff or getattr(utente, 'dipendente', None) is not None)


def percentuali(produzione):
    """{prodotto_id: percentuale sul totale del suo impianto nel turno}."""
    righe = list(produzione.righe.select_related('prodotto'))
    totali = {}
    for r in righe:
        totali[r.prodotto.impianto] = totali.get(r.prodotto.impianto, 0) + r.tonnellate
    return {r.prodotto_id: (r.tonnellate * 100 / totali[r.prodotto.impianto]) if totali[r.prodotto.impianto] else None for r in righe}


def medie(fino_a, giorni=30):
    """Media delle percentuali di ogni prodotto nei turni degli ultimi 30 giorni (escluso il turno stesso)."""
    somme, conti = {}, {}
    for p in ProduzioneTurno.objects.filter(data__gte=fino_a - timedelta(days=giorni), data__lte=fino_a).prefetch_related('righe__prodotto'):
        for pid, perc in percentuali(p).items():
            if perc is not None:
                somme[pid] = somme.get(pid, 0) + perc
                conti[pid] = conti.get(pid, 0) + 1
    return {pid: somme[pid] / conti[pid] for pid in somme}


def confronto(produzione, media):
    """Righe per la tabella: prodotto, tonnellate, %, media, se è uno scarto sopra la soglia."""
    perc = percentuali(produzione)
    righe = []
    for r in produzione.righe.select_related('prodotto').order_by('prodotto__impianto', 'prodotto__ordine'):
        p, m = perc.get(r.prodotto_id), media.get(r.prodotto_id)
        alto = bool(r.prodotto.categoria == ProdottoProduzione.Categoria.SCARTO and p is not None and m and p > m * SOGLIA)
        righe.append({'r': r, 'perc': p, 'media': m, 'alto': alto})
    return righe


def turno_corrente():
    ora = timezone.localtime()
    if ora.hour >= 22 or ora.hour < 6:
        giorno = ora.date() if ora.hour >= 22 else ora.date() - timedelta(days=1)
        return giorno, 'N'
    return ora.date(), '1T' if ora.hour < 14 else '2T'


def turno_da_ora(data, ora):
    """Data e ora scritte sul display ('2026-10-21', '21:41') -> ('2026-10-21', '2T'). La notte dopo
    mezzanotte appartiene al giorno prima, come nei turni."""
    from datetime import date

    giorno, ore = date.fromisoformat(data), int(ora.split(':')[0])
    if ore < 6:
        return (giorno - timedelta(days=1)).isoformat(), 'N'
    if ore >= 22:
        return giorno.isoformat(), 'N'
    return giorno.isoformat(), '1T' if ore < 14 else '2T'


# impianti della pesa: per Metalli e Sabbia le righe del display non sono ancora definite
IMPIANTI = [('IMP1', 'Impianto 1', '🏭'), ('IMP2', 'Impianto 2', '🏭'), ('MET', 'Metalli', '🔩'), ('SAB', 'Sabbia', '⏳')]


@login_required
def produzione(request):
    if not puo_vedere(request.user):
        raise PermissionDenied
    oggi = timezone.localdate()
    media = medie(oggi)
    turni = list(ProduzioneTurno.objects.filter(data__gte=oggi - timedelta(days=14)).prefetch_related('righe__prodotto'))
    scarti = list(ProdottoProduzione.objects.filter(attivo=True, categoria=ProdottoProduzione.Categoria.SCARTO))
    for t in turni:
        perc = percentuali(t)
        t.scarti = [{'p': s, 'perc': perc.get(s.pk), 'alto': perc.get(s.pk) is not None and media.get(s.pk) and perc[s.pk] > media[s.pk] * SOGLIA}
                    for s in scarti]
        t.totale = sum(r.tonnellate for r in t.righe.all())
    return render(request, 'turni/produzione.html', {
        'turni': turni, 'scarti': scarti, 'media': [(s, media.get(s.pk)) for s in scarti],
    })


@login_required
def produzione_turno(request, produzione_id=None):
    if not puo_vedere(request.user):
        raise PermissionDenied
    esistente = get_object_or_404(ProduzioneTurno, pk=produzione_id) if produzione_id else None
    impianto = request.POST.get('impianto') or request.GET.get('impianto') or ''
    nomi = {c: n for c, n, _ in IMPIANTI}
    if not esistente and impianto not in nomi and request.method == 'GET':
        # prima si sceglie l'impianto, poi la foto del suo display
        return render(request, 'turni/produzione_impianto.html', {'impianti': IMPIANTI})
    prodotti = list(ProdottoProduzione.objects.filter(attivo=True))
    if impianto in nomi:
        prodotti = [p for p in prodotti if p.impianto == impianto]
    if request.method == 'POST':
        from datetime import date

        try:
            giorno = date.fromisoformat(request.POST.get('data') or '')
        except ValueError:
            giorno = None
        fascia = request.POST.get('fascia')
        valori = {}
        errore = None
        for p in prodotti:
            testo = (request.POST.get(f'p{p.pk}') or '').strip().replace(',', '.')
            if not testo:
                continue
            try:
                v = Decimal(testo).quantize(Decimal('0.01'))
                if v < 0 or v > 100000:
                    raise InvalidOperation
                valori[p] = v
            except InvalidOperation:
                errore = f'Valore non valido per {p.nome}.'
        if errore or not giorno or fascia not in dict(ProduzioneTurno.FASCE) or not valori:
            messages.error(request, errore or 'Indica giorno, turno e almeno un valore.')
        else:
            t, _ = ProduzioneTurno.objects.get_or_create(data=giorno, fascia=fascia, defaults={'inserita_da': request.user})
            t.inserita_da, t.inserita_il = request.user, timezone.now()
            t.note = (request.POST.get('note') or '').strip()[:500]
            if request.FILES.get('foto'):
                try:
                    t.foto.save('display.jpg', mn.comprimi_foto(request.FILES['foto']), save=False)
                except (ValueError, OSError):
                    messages.error(request, 'La foto non è valida: valori salvati senza foto.')
            t.save()
            # si toccano solo le righe dell'impianto inserito: gli altri impianti dello stesso turno restano
            t.righe.filter(prodotto__in=prodotti).exclude(prodotto__in=list(valori)).delete()
            for p, v in valori.items():
                RigaProduzione.objects.update_or_create(produzione=t, prodotto=p, defaults={'tonnellate': v})
            alti = [x for x in confronto(t, medie(giorno - timedelta(days=1))) if x['alto']]
            if alti:
                testo = ', '.join(f"{x['r'].prodotto.nome} {x['perc']:.1f}% (media {x['media']:.1f}%)" for x in alti)
                mn.avvisa(mn.responsabili(), request.user, f'📊 Scarto alto · {t}', testo, reverse('turni:produzione_turno', args=[t.pk]))
            messages.success(request, 'Produzione del turno salvata.')
            return redirect('turni:produzione_turno', t.pk)
    if esistente and request.method == 'GET' and not request.GET.get('modifica'):
        return render(request, 'turni/produzione_turno.html', {
            't': esistente, 'righe': confronto(esistente, medie(esistente.data - timedelta(days=1))),
        })
    giorno, fascia = (esistente.data, esistente.fascia) if esistente else turno_corrente()
    valori = {r.prodotto_id: r.tonnellate for r in esistente.righe.all()} if esistente else {}
    for p in prodotti:
        p.valore = valori.get(p.pk, '')
    return render(request, 'turni/produzione_nuova.html', {
        'prodotti': prodotti, 'giorno': giorno, 'fascia': fascia, 'fasce': ProduzioneTurno.FASCE, 'esistente': esistente,
        'impianto': impianto, 'nome_impianto': nomi.get(impianto, ''),
        'sigla': {'1T': '1T', '2T': '2T', 'N': 'N'}.get(fascia, ''),
        'classe': {'1T': 'f-mattina', '2T': 'f-pomeriggio', 'N': 'f-notte'}.get(fascia, ''),
        'leggi_foto': __import__('turni.lettura', fromlist=['attiva']).attiva(),
    })


@login_required
def foto_produzione(request, produzione_id):
    if not puo_vedere(request.user):
        raise PermissionDenied
    t = get_object_or_404(ProduzioneTurno, pk=produzione_id)
    if not t.foto:
        raise Http404
    return FileResponse(t.foto.open('rb'), content_type='image/jpeg')
