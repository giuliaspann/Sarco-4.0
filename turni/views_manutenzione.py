"""Manutenzione: guasti, interventi, macchine, ricambi, ordini, programmate."""

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from . import manutenzione as mn
from .accessi import qr_svg
from .esempi_manutenzione import togli
from .models import Intervento, Luogo, Macchina, ManutenzioneProgrammata, OrdineRicambio, Ricambio

LUOGHI_BREVI = [('IMP1', 'Imp. 1'), ('IMP2', 'Imp. 2'), ('PIAZZALE', 'Piazzale'), ('METALLI', 'Metalli'), ('SABBIA', 'Sabbia'), ('MEZZI', 'Mezzi interni')]


class MacchinaForm(forms.ModelForm):
    class Meta:
        model = Macchina
        fields = ['nome', 'codice', 'luogo', 'tipo', 'categoria', 'marca', 'modello', 'matricola', 'anno', 'contaore', 'note']
        widgets = {'note': forms.Textarea(attrs={'rows': 2})}


class RicambioForm(forms.ModelForm):
    class Meta:
        model = Ricambio
        fields = ['nome', 'codice', 'scorta', 'scorta_minima', 'unita', 'ubicazione', 'fornitore', 'macchine']


class ProgrammataForm(forms.ModelForm):
    class Meta:
        model = ManutenzioneProgrammata
        fields = ['macchina', 'attivita', 'ogni_giorni', 'ultima', 'istruzioni']
        widgets = {'ultima': forms.DateInput(attrs={'type': 'date'}), 'istruzioni': forms.Textarea(attrs={'rows': 3})}


def _permessi(utente):
    return {
        'resp': mn.e_resp(utente),
        'approvatore': mn.puo_approvare(utente),
        'manutentore': mn.e_manutentore(utente),
        'chiede_pezzi': mn.puo_chiedere_pezzi(utente),
        'ordina': mn.puo_ordinare(utente),
    }


def _luogo(request):
    luogo = request.GET.get('luogo', '')
    return luogo if luogo in Luogo.values else ''


@login_required
def manutenzione(request):
    mn.genera_programmate()
    luogo = _luogo(request)
    aperti = Intervento.objects.filter(stato__in=Intervento.APERTI).select_related('macchina', 'assegnata_a')
    if luogo:
        aperti = aperti.filter(macchina__luogo=luogo)
    aperti = list(aperti)
    dip = mn.dipendente_di(request.user)
    permessi = _permessi(request.user)
    da_approvare = [i for i in aperti if i.stato == Intervento.Stato.SEGNALATA] if permessi['approvatore'] else []
    miei = [i for i in aperti if dip and i.assegnata_a_id == dip.pk and i not in da_approvare]
    altri = [i for i in aperti if i not in da_approvare and i not in miei]
    recenti = Intervento.objects.filter(
        stato=Intervento.Stato.COMPLETATA, completata_il__gte=timezone.now() - timedelta(days=7)
    ).select_related('macchina').order_by('-completata_il')
    if luogo:
        recenti = recenti.filter(macchina__luogo=luogo)
    return render(request, 'turni/mn_home.html', {
        **permessi, 'luogo': luogo, 'luoghi': LUOGHI_BREVI, 'scheda': 'interventi',
        'da_approvare': da_approvare, 'miei': miei, 'altri': altri, 'recenti': recenti[:5],
        'aperti_totale': len(aperti),
        'ferme': sum(1 for i in aperti if i.macchina_ferma),
        'sotto_scorta': sum(1 for r in Ricambio.objects.all() if r.sotto_scorta) if permessi['chiede_pezzi'] else 0,
        'ordini_aperti': OrdineRicambio.objects.filter(
            stato__in=[OrdineRicambio.Stato.RICHIESTO, OrdineRicambio.Stato.APPROVATO, OrdineRicambio.Stato.ORDINATO]
        ).count(),
    })


ICONE_LUOGHI = {'IMP1': '🏭', 'IMP2': '🏭', 'PIAZZALE': '🅿️', 'METALLI': '🔩', 'SABBIA': '⏳', 'MEZZI': '🚜'}


@login_required
def segnala(request):
    """In tre passi senza menu a tendina: luogo → macchina (pulsanti grandi, con ricerca) → cosa succede e foto."""
    macchine = Macchina.objects.filter(attiva=True)
    scelta = request.POST.get('macchina') or request.GET.get('macchina') or ''
    macchina = macchine.filter(pk=scelta).first() if scelta.isdigit() else None
    if request.method == 'POST':
        descrizione = (request.POST.get('descrizione') or '').strip()[:1000]
        foto = request.FILES.get('foto')
        if not (macchina and descrizione and foto):
            messages.error(request, 'Scrivi cosa succede e fai la foto del guasto.')
        else:
            try:
                i = mn.segnala(request.user, macchina, descrizione, request.POST.get('ferma') == '1', foto)
            except (ValueError, OSError):
                messages.error(request, 'La foto non è valida: riprova.')
            else:
                messages.success(request, 'Segnalazione inviata: il capo turno e il responsabile manutenzione la ricevono subito.')
                return redirect('turni:intervento', i.pk)
    contesto = {'macchina': macchina, 'descrizione': request.POST.get('descrizione', '')}
    if macchina is None:
        luogo = _luogo(request)
        q = (request.GET.get('q') or '').strip()
        if luogo or q:
            elenco = macchine.filter(luogo=luogo) if luogo else macchine
            if q:
                elenco = elenco.filter(Q(nome__icontains=q) | Q(codice__icontains=q) | Q(categoria__icontains=q) | Q(marca__icontains=q))
            contesto.update(luogo=luogo, nome_luogo=Luogo(luogo).label if luogo else '', q=q,
                            elenco=mn.stato_macchine(list(elenco)))
        else:
            conti = {v: 0 for v in Luogo.values}
            for v in macchine.values_list('luogo', flat=True):
                conti[v] += 1
            contesto['luoghi'] = [(v, nome, ICONE_LUOGHI[v], conti[v]) for v, nome in Luogo.choices if conti[v]]
    return render(request, 'turni/mn_segnala.html', contesto)


@login_required
def intervento(request, intervento_id):
    i = get_object_or_404(Intervento.objects.select_related('macchina', 'assegnata_a', 'segnalata_da', 'piano'), pk=intervento_id)
    permessi = _permessi(request.user)
    lavora = mn.puo_lavorare(request.user, i)
    if request.method == 'POST':
        azione = request.POST.get('azione')
        if azione == 'approva' and i.stato == Intervento.Stato.SEGNALATA and permessi['approvatore'] or \
                azione == 'riassegna' and i.aperto and permessi['resp']:
            dip = next((d for d in mn.manutentori() if str(d.pk) == request.POST.get('manutentore')), None)
            if not dip:
                messages.error(request, 'Scegli il manutentore.')
            elif azione == 'approva':
                p = request.POST.get('priorita')
                mn.approva(request.user, i, dip, int(p) if p in ('1', '2', '3', '4') else None)
                messages.success(request, f'Inviato a {dip.nome_breve}.')
            else:
                i.assegnata_a = dip
                i.save(update_fields=['assegnata_a'])
                mn.evento(i, request.user, f'Riassegnato a {dip.nome_breve}')
                mn.avvisa([dip.utente_id], request.user, f'Intervento assegnato · {i.macchina.nome}', i.descrizione, mn.url_intervento(i))
        elif azione == 'rifiuta' and i.stato == Intervento.Stato.SEGNALATA and permessi['approvatore']:
            mn.rifiuta(request.user, i, (request.POST.get('motivo') or '').strip()[:300])
        elif azione == 'inizia' and i.stato == Intervento.Stato.ASSEGNATA and lavora:
            mn.inizia(request.user, i)
        elif azione == 'completa' and i.aperto and i.stato != Intervento.Stato.SEGNALATA and lavora:
            lavoro = (request.POST.get('lavoro') or '').strip()[:2000]
            foto = request.FILES.get('foto')
            try:
                ore = Decimal(request.POST.get('ore') or '0').quantize(Decimal('0.1')) or None
                if ore is not None and not (0 < ore < 1000):
                    raise InvalidOperation
            except InvalidOperation:
                ore = None
            pezzi = _pezzi_usati(request)
            if not (lavoro and foto):
                messages.error(request, 'Scrivi cosa hai fatto e fai la foto della macchina riparata.')
            else:
                try:
                    mn.completa(request.user, i, lavoro, foto, ore, pezzi)
                except (ValueError, OSError):
                    messages.error(request, 'La foto non è valida: riprova.')
                else:
                    messages.success(request, 'Intervento chiuso. Grazie!')
        elif azione == 'nota':
            testo = (request.POST.get('testo') or '').strip()
            if testo:
                mn.evento(i, request.user, testo, nota=True)
        return redirect('turni:intervento', i.pk)

    in_turno, altri = mn.manutentori_di_turno()
    compatibili = list(i.macchina.ricambi.all())
    return render(request, 'turni/mn_intervento.html', {
        **permessi, 'i': i, 'lavora': lavora, 'in_turno': in_turno, 'altri_manutentori': altri,
        'priorita': Intervento.Priorita.choices,
        'ricambi': compatibili + [r for r in Ricambio.objects.all() if r not in compatibili],
        'righe_pezzi': range(3),
        'eventi': i.eventi.select_related('autore', 'autore__dipendente'),
        'ordini': i.ordini.select_related('ricambio'),
    })


def _pezzi_usati(request):
    pezzi = []
    for n in range(3):
        rid, testo = request.POST.get(f'pezzo_{n}'), (request.POST.get(f'altro_{n}') or '').strip()[:100]
        try:
            quantita = max(1, min(999, int(request.POST.get(f'quantita_{n}') or 1)))
        except ValueError:
            quantita = 1
        ricambio = Ricambio.objects.filter(pk=rid).first() if (rid or '').isdigit() else None
        if ricambio or testo:
            pezzi.append((ricambio, '' if ricambio else testo, quantita))
    return pezzi


@login_required
def foto(request, tipo, oggetto_id):
    if tipo == 'ordine':
        f = get_object_or_404(OrdineRicambio, pk=oggetto_id).foto
    elif tipo in ('guasto', 'riparazione'):
        f = getattr(get_object_or_404(Intervento, pk=oggetto_id), f'foto_{tipo}')
    else:
        raise Http404
    if not f:
        raise Http404
    return FileResponse(f.open('rb'), content_type='image/jpeg')


@login_required
def macchine(request):
    permessi = _permessi(request.user)
    if request.method == 'POST' and permessi['resp']:
        if request.POST.get('azione') == 'togli_esempi':
            messages.success(request, f'Tolte {togli()} macchine d\'esempio con i loro interventi.')
            return redirect('turni:macchine')
        form = MacchinaForm(request.POST)
        if form.is_valid():
            m = form.save()
            messages.success(request, f'{m.nome} aggiunta.')
            return redirect('turni:macchina', m.pk)
    else:
        form = MacchinaForm()
    luogo = _luogo(request)
    q = (request.GET.get('q') or '').strip()
    elenco = Macchina.objects.filter(attiva=True)
    if luogo:
        elenco = elenco.filter(luogo=luogo)
    if q:
        elenco = elenco.filter(Q(nome__icontains=q) | Q(codice__icontains=q) | Q(categoria__icontains=q) | Q(marca__icontains=q))
    elenco = mn.stato_macchine(list(elenco))
    gruppi = [(nome, [m for m in elenco if m.luogo == v]) for v, nome in Luogo.choices]
    return render(request, 'turni/mn_macchine.html', {
        **permessi, 'scheda': 'macchine', 'luogo': luogo, 'luoghi': LUOGHI_BREVI, 'q': q,
        'gruppi': [g for g in gruppi if g[1]], 'form': form,
        'ci_sono_esempi': Macchina.objects.filter(esempio=True).exists(),
    })


@login_required
def macchina(request, macchina_id):
    m = get_object_or_404(Macchina, pk=macchina_id)
    permessi = _permessi(request.user)
    form = None
    if permessi['resp']:
        form = MacchinaForm(request.POST or None, instance=m)
        if request.method == 'POST' and request.POST.get('azione') == 'modifica' and form.is_valid():
            form.save()
            messages.success(request, 'Scheda aggiornata.')
            return redirect('turni:macchina', m.pk)
    if request.method == 'POST' and request.POST.get('azione') == 'contaore' and (permessi['manutentore'] or permessi['resp']):
        try:
            m.contaore = max(0, int(request.POST.get('contaore')))
            m.save(update_fields=['contaore'])
        except (TypeError, ValueError):
            messages.error(request, 'Scrivi le ore come numero.')
        return redirect('turni:macchina', m.pk)
    mn.stato_macchine([m])
    interventi = m.interventi.select_related('assegnata_a').order_by('-segnalata_il')
    return render(request, 'turni/mn_macchina.html', {
        **permessi, 'm': m, 'form': form,
        'aperti': [i for i in interventi if i.aperto],
        'storico': [i for i in interventi if not i.aperto][:20],
        'programmate': m.programmate.filter(attiva=True),
        'ricambi': m.ricambi.all(),
        'stat': mn.statistiche(m),
    })


@login_required
def ricambi(request):
    permessi = _permessi(request.user)
    if request.method == 'POST' and permessi['chiede_pezzi']:
        if request.POST.get('azione') == 'scorta':
            r = get_object_or_404(Ricambio, pk=request.POST.get('ricambio'))
            r.scorta = max(0, r.scorta + (1 if request.POST.get('verso') == 'piu' else -1))
            r.save(update_fields=['scorta'])
            return redirect(f"{reverse('turni:ricambi')}?{request.GET.urlencode()}#r{r.pk}")
        form = RicambioForm(request.POST)
        if form.is_valid():
            r = form.save()
            messages.success(request, f'{r.nome} aggiunto al magazzino.')
            return redirect('turni:ricambi')
    else:
        form = RicambioForm()
    q = (request.GET.get('q') or '').strip()
    elenco = Ricambio.objects.prefetch_related('macchine')
    if q:
        elenco = elenco.filter(Q(nome__icontains=q) | Q(codice__icontains=q) | Q(macchine__nome__icontains=q)).distinct()
    elenco = list(elenco)
    sotto = request.GET.get('sotto') == '1'
    if sotto:
        elenco = [r for r in elenco if r.sotto_scorta]
    return render(request, 'turni/mn_ricambi.html', {
        **permessi, 'scheda': 'ricambi', 'elenco': elenco, 'q': q, 'sotto': sotto, 'form': form,
    })


@login_required
def ordini(request):
    permessi = _permessi(request.user)
    if request.method == 'POST':
        o = get_object_or_404(OrdineRicambio, pk=request.POST.get('ordine'))
        if mn.avanza_ordine(request.user, o, request.POST.get('azione'), request.POST.get('fornitore') or ''):
            messages.success(request, f'{o.nome}: {o.get_stato_display().lower()}.')
        return redirect('turni:ordini')
    tutti = OrdineRicambio.objects.select_related('ricambio', 'macchina', 'intervento', 'richiesto_da', 'richiesto_da__dipendente')
    S = OrdineRicambio.Stato
    gruppi = [
        ('Da approvare', tutti.filter(stato=S.RICHIESTO)),
        ('Da ordinare', tutti.filter(stato=S.APPROVATO)),
        ('Ordinati, in arrivo', tutti.filter(stato=S.ORDINATO)),
        ('Arrivati negli ultimi 30 giorni', tutti.filter(stato=S.ARRIVATO, arrivato_il__gte=timezone.now() - timedelta(days=30))),
    ]
    return render(request, 'turni/mn_ordini.html', {**permessi, 'scheda': 'ordini', 'gruppi': gruppi})


@login_required
def nuovo_ordine(request):
    if not mn.puo_chiedere_pezzi(request.user):
        raise PermissionDenied
    sorgente = request.POST if request.method == 'POST' else request.GET
    i = Intervento.objects.filter(pk=sorgente.get('intervento')).select_related('macchina').first() if (sorgente.get('intervento') or '').isdigit() else None
    ricambio_scelto = sorgente.get('ricambio') or ''
    if request.method == 'POST':
        ricambio = Ricambio.objects.filter(pk=ricambio_scelto).first() if ricambio_scelto.isdigit() else None
        descrizione = (request.POST.get('descrizione') or '').strip()[:120]
        foto = request.FILES.get('foto')
        try:
            quantita = max(1, min(9999, int(request.POST.get('quantita') or 1)))
        except ValueError:
            quantita = 1
        if not (ricambio or descrizione):
            messages.error(request, 'Scegli il pezzo dal magazzino o scrivi quale serve.')
        elif not (i or foto):
            messages.error(request, 'Serve la foto della macchina o del pezzo rotto.')
        else:
            try:
                mn.chiedi_pezzo(request.user, ricambio, '' if ricambio else descrizione, quantita,
                                request.POST.get('urgente') == '1', (request.POST.get('nota') or '').strip()[:300],
                                intervento=i, foto=foto)
            except (ValueError, OSError):
                messages.error(request, 'La foto non è valida: riprova.')
            else:
                messages.success(request, 'Richiesta del pezzo inviata.')
                return redirect('turni:intervento', i.pk) if i else redirect('turni:ordini')
    compatibili = list(i.macchina.ricambi.all()) if i else []
    return render(request, 'turni/mn_ordine_nuovo.html', {
        'i': i, 'ricambio_scelto': ricambio_scelto,
        'compatibili': compatibili, 'altri': [r for r in Ricambio.objects.all() if r not in compatibili],
    })


@login_required
def programmate(request):
    permessi = _permessi(request.user)
    form = ProgrammataForm(request.POST or None) if permessi['resp'] else None
    if request.method == 'POST' and permessi['resp']:
        if request.POST.get('azione') == 'disattiva':
            p = get_object_or_404(ManutenzioneProgrammata, pk=request.POST.get('piano'))
            p.attiva = False
            p.save(update_fields=['attiva'])
            return redirect('turni:programmate')
        if form.is_valid():
            form.save()
            mn.genera_programmate()
            messages.success(request, 'Manutenzione programmata aggiunta.')
            return redirect('turni:programmate')
    oggi = timezone.localdate()
    piani = list(ManutenzioneProgrammata.objects.filter(attiva=True, macchina__attiva=True).select_related('macchina'))
    for p in piani:
        p.giorni = (p.prossima - oggi).days
    piani.sort(key=lambda p: p.prossima)
    return render(request, 'turni/mn_programmate.html', {**permessi, 'scheda': 'programmate', 'piani': piani, 'form': form})


@login_required
def etichette(request):
    if not (mn.e_resp(request.user) or request.user.is_staff):
        raise PermissionDenied
    base = request.build_absolute_uri(reverse('turni:segnala'))
    luogo = _luogo(request)
    elenco = list(Macchina.objects.filter(attiva=True, **({'luogo': luogo} if luogo else {})))
    for m in elenco:
        m.qr = qr_svg(f'{base}?macchina={m.pk}')
    return render(request, 'turni/mn_etichette.html', {'elenco': elenco, 'luogo': luogo, 'luoghi': LUOGHI_BREVI})

