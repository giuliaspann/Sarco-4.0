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
from .models import Comunicazione, Dipendente, FermoImpianto, FotoComunicazione, FotoIntervento, Intervento, Luogo, Macchina, ManutenzioneProgrammata, OrdineRicambio, Ricambio

# prima si sceglie il gruppo, poi il luogo
GRUPPI = [
    ('macchinari', 'Macchinari e attrezzature', '🏭', ['IMP1', 'IMP2', 'PIAZZALE', 'METALLI', 'SABBIA', 'ANALISI']),
    ('mezzi', 'Mezzi', '🚚', ['MEZZI', 'ESTERNI']),
    ('segnaletica', 'Segnaletica e Cartelli', '🪧', ['PIAZZALE', 'IMP1', 'IMP2', 'METALLI', 'SABBIA', 'ANALISI']),
]


def cond_gruppo(gruppo, luogo='', prefisso=''):
    """Filtro sulle macchine (o, con prefisso 'macchina__', sugli interventi) per gruppo e luogo."""
    voce = next((x for x in GRUPPI if x[0] == gruppo), None)
    q = Q()
    if luogo:
        q &= Q(**{prefisso + 'luogo': luogo})
    elif voce:
        q &= Q(**{prefisso + 'luogo__in': voce[3]})
    if gruppo == 'segnaletica':
        q &= Q(**{prefisso + 'tipo': Macchina.Tipo.SEGNALETICA})
    elif gruppo:
        q &= ~Q(**{prefisso + 'tipo': Macchina.Tipo.SEGNALETICA})
    return q
ICONE_LUOGHI = {'ANALISI': '🧪', 'IMP1': '🏭', 'IMP2': '🏭', 'PIAZZALE': '🅿️', 'METALLI': '🔩', 'SABBIA': '⏳', 'MEZZI': '🚜', 'ESTERNI': '🚛'}


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


def _filtro(request):
    """Filtro a due livelli: gruppo (macchinari / mezzi / segnaletica) e poi luogo.
    Restituisce il contesto e una funzione che dà la condizione (con prefisso per gli interventi)."""
    luogo = _luogo(request)
    gruppo = request.GET.get('gruppo', '')
    if gruppo not in [g for g, _, _, _ in GRUPPI]:
        gruppo = next((g for g, _, _, luoghi in GRUPPI if luogo in luoghi), '') if luogo else ''
    voce = next((x for x in GRUPPI if x[0] == gruppo), None)
    return {
        'gruppo': gruppo, 'luogo': luogo, 'gruppi_filtro': GRUPPI,
        'sotto': [(v, Luogo(v).label) for v in voce[3]] if voce else [],
    }, (lambda prefisso='': cond_gruppo(gruppo, luogo, prefisso))


@login_required
def manutenzione(request):
    """Pagina iniziale: un pulsante per riga, con i numeri che contano."""
    mn.genera_programmate()
    permessi = _permessi(request.user)
    dip = mn.dipendente_di(request.user)
    aperti = Intervento.objects.filter(stato__in=Intervento.APERTI)
    badge_interventi = aperti.filter(assegnata_a=dip, stato=Intervento.Stato.ASSEGNATA).count() if dip else 0
    if permessi['approvatore']:
        badge_interventi += aperti.filter(stato=Intervento.Stato.SEGNALATA).count()
    S = OrdineRicambio.Stato
    badge_ordini = OrdineRicambio.objects.filter(stato=S.RICHIESTO).count() if permessi['resp'] else 0
    if dip and dip.acquisti:
        badge_ordini += OrdineRicambio.objects.filter(stato=S.APPROVATO).count()
    entro = timezone.localdate() + timedelta(days=3)
    return render(request, 'turni/mn_home.html', {
        'registra_lavoro': mn.puo_registrare_lavoro(request.user),
        'comunicazioni_aperte': Comunicazione.objects.exclude(stato=Comunicazione.Stato.RISOLTA).count(),
        'puo_comunicare': mn.puo_comunicare(request.user),
        'fermi_in_corso': FermoImpianto.objects.filter(ripartito_il__isnull=True).order_by('fermo_dal'),
        'aperti': aperti.count(),
        'ferme': aperti.filter(macchina_ferma=True, tipo=Intervento.Tipo.GUASTO).count(),
        'badge_interventi': badge_interventi, 'badge_ordini': badge_ordini,
        'sotto_scorta': sum(1 for r in Ricambio.objects.all() if r.sotto_scorta),
        'ordini_aperti': OrdineRicambio.objects.filter(stato__in=[S.RICHIESTO, S.APPROVATO, S.ORDINATO]).count(),
        'in_scadenza': sum(1 for p in ManutenzioneProgrammata.objects.filter(attiva=True) if p.prossima <= entro),
    })


@login_required
def interventi(request):
    mn.genera_programmate()
    filtro, cond = _filtro(request)
    aperti = Intervento.objects.filter(stato__in=Intervento.APERTI).select_related('macchina', 'assegnata_a', 'segnalata_da__dipendente')
    aperti = aperti.filter(cond('macchina__'))
    aperti = list(aperti)
    dip = mn.dipendente_di(request.user)
    permessi = _permessi(request.user)
    da_approvare = [i for i in aperti if i.stato == Intervento.Stato.SEGNALATA] if permessi['approvatore'] else []
    miei = [i for i in aperti if dip and i.assegnata_a_id == dip.pk and i not in da_approvare]
    altri = [i for i in aperti if i not in da_approvare and i not in miei]
    recenti = Intervento.objects.filter(
        stato=Intervento.Stato.COMPLETATA, completata_il__gte=timezone.now() - timedelta(days=30)
    ).select_related('macchina', 'assegnata_a', 'segnalata_da__dipendente', 'completata_da__dipendente').order_by('-completata_il')
    recenti = recenti.filter(cond('macchina__'))
    return render(request, 'turni/mn_interventi.html', {
        **permessi, **filtro, 'mostra_gruppi': True,
        'da_approvare': da_approvare, 'miei': miei, 'altri': altri, 'recenti': recenti[:30],
        'aperti_totale': len(aperti),
        'ferme': sum(1 for i in aperti if i.macchina_ferma),
        'sotto_scorta': sum(1 for r in Ricambio.objects.all() if r.sotto_scorta) if permessi['chiede_pezzi'] else 0,
        'ordini_aperti': OrdineRicambio.objects.filter(
            stato__in=[OrdineRicambio.Stato.RICHIESTO, OrdineRicambio.Stato.APPROVATO, OrdineRicambio.Stato.ORDINATO]
        ).count(),
    })


@login_required
def segnala(request):
    """Senza menu a tendina: macchinari o mezzi → luogo → macchina (pulsanti grandi, con ricerca) → guasto e foto."""
    macchine = Macchina.objects.filter(attiva=True)
    scelta = request.POST.get('macchina') or request.GET.get('macchina') or ''
    macchina = macchine.filter(pk=scelta).first() if scelta.isdigit() else None
    lavoro = (request.POST.get('lavoro') or request.GET.get('lavoro')) == '1'
    programma = not lavoro and (request.POST.get('programma') or request.GET.get('programma')) == '1'
    if lavoro and not mn.puo_registrare_lavoro(request.user) or programma and not mn.puo_chiedere_pezzi(request.user):
        raise PermissionDenied
    if request.method == 'POST' and programma:
        from datetime import date

        attivita = (request.POST.get('attivita') or '').strip()[:120]
        try:
            quando = date.fromisoformat(request.POST.get('quando') or '')
        except ValueError:
            quando = None
        ogni = request.POST.get('ogni') or '0'
        ogni = int(ogni) if ogni in ('0', '7', '14', '30', '90', '180', '365') else 0
        if not (macchina and attivita and quando):
            messages.error(request, 'Scrivi cosa va fatto e quando.')
        else:
            mn.programma(request.user, macchina, attivita, quando, ogni, (request.POST.get('istruzioni') or '').strip()[:1000])
            messages.success(request, 'Manutenzione programmata.')
            return redirect('turni:segnala')
    if request.method == 'POST' and lavoro:
        testo = (request.POST.get('descrizione') or '').strip()[:1000]
        foto = request.FILES.getlist('foto')
        try:
            ore = Decimal(request.POST.get('ore') or '0').quantize(Decimal('0.1')) or None
            if ore is not None and not (0 < ore < 1000):
                raise InvalidOperation
        except InvalidOperation:
            ore = None
        tipo_lavoro = request.POST.get('tipo_lavoro') or ''
        tipo_lavoro = tipo_lavoro if tipo_lavoro in dict(Intervento._meta.get_field('tipo_lavoro').choices) else ''
        pezzo = (request.POST.get('pezzo') or '').strip()[:100]
        testo = testo or ' · '.join(x for x in (dict(Intervento._meta.get_field('tipo_lavoro').choices).get(tipo_lavoro, ''), pezzo) if x)
        if not (macchina and testo and foto):
            messages.error(request, 'Scegli cosa hai fatto e aggiungi almeno una foto.')
        else:
            try:
                video = mn.controlla_video(request.FILES.get('video'))
                i = mn.registra_lavoro(request.user, macchina, testo, foto, ore, _pezzi_usati(request), tipo_lavoro, pezzo)
                mn.dopo_il_lavoro(request.user, i, _collaboratori(request), (request.POST.get('resta') or '').strip()[:1000], video)
            except (ValueError, OSError):
                messages.error(request, 'Una delle foto o il video non sono validi (video: massimo 50 MB).')
            else:
                messages.success(request, 'Manutenzione registrata nello storico della macchina.')
                return redirect('turni:intervento', i.pk)
    elif request.method == 'POST':
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
    contesto = {'macchina': macchina, 'descrizione': request.POST.get('descrizione', ''),
                'lavoro': lavoro, 'programma': programma,
                'pre': 'lavoro=1&' if lavoro else ('programma=1&' if programma else '')}
    if macchina and programma:
        contesto.update(domani=timezone.localdate() + timedelta(days=1), ripetizioni=[
            ('0', 'Una volta'), ('7', 'Ogni settimana'), ('14', 'Ogni 2 settimane'), ('30', 'Ogni mese'),
            ('90', 'Ogni 3 mesi'), ('365', "Ogni anno")])
    if macchina and lavoro:
        contesto['tipi_lavoro'] = Intervento._meta.get_field('tipo_lavoro').choices
        compatibili = list(macchina.ricambi.all())
        contesto.update(ricambi=compatibili + [r for r in Ricambio.objects.all() if r not in compatibili], righe_pezzi=range(3),
                        **_scelta_colleghi(request.user))
    if macchina is None:
        luogo = _luogo(request)
        q = (request.GET.get('q') or '').strip()
        g = request.GET.get('gruppo', '')
        g = g if g in [x for x, _, _, _ in GRUPPI] else ''
        if luogo and g == 'segnaletica' and not q and not macchine.filter(cond_gruppo(g, luogo)).exists():
            # nessun cartello in elenco per quel luogo: si segnala sulla "segnaletica" del luogo, basta commento e foto
            m, _ = Macchina.objects.get_or_create(codice=f'SEG-{luogo}', defaults={
                'nome': f'Segnaletica {Luogo(luogo).label}', 'tipo': Macchina.Tipo.SEGNALETICA, 'luogo': luogo})
            return redirect(f"{reverse('turni:segnala')}?{contesto['pre']}macchina={m.pk}")
        if luogo or q:
            elenco = macchine.filter(cond_gruppo(g, luogo))
            if q:
                elenco = elenco.filter(Q(nome__icontains=q) | Q(codice__icontains=q) | Q(categoria__icontains=q) | Q(marca__icontains=q))
            contesto.update(luogo=luogo, nome_luogo=Luogo(luogo).label if luogo else '', q=q,
                            gruppo_luogo=g or next((x for x, _, _, luoghi in GRUPPI if luogo in luoghi), ''),
                            elenco=mn.stato_macchine(list(elenco)))
        else:
            gruppo = next((x for x in GRUPPI if x[0] == g), None)
            if gruppo:
                contesto['gruppo'] = gruppo
                luoghi = [(v, Luogo(v).label, ICONE_LUOGHI[v], macchine.filter(cond_gruppo(g, v)).count()) for v in gruppo[3]]
                contesto['luoghi'] = luoghi  # tutti i luoghi, anche dove l'elenco è ancora vuoto
            else:
                contesto['gruppi'] = [(x, nome, icona, macchine.filter(cond_gruppo(x)).count()) for x, nome, icona, _ in GRUPPI]
                if not lavoro and not programma:
                    mn.genera_programmate()
                    contesto.update(mn.calendario_manutenzioni(), puo_programmare=mn.puo_chiedere_pezzi(request.user))
    return render(request, 'turni/mn_segnala.html', contesto)


@login_required
def intervento(request, intervento_id):
    i = get_object_or_404(Intervento.objects.select_related('macchina', 'assegnata_a', 'segnalata_da__dipendente', 'approvata_da__dipendente', 'completata_da__dipendente', 'piano'), pk=intervento_id)
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
                _quando_e_dove(request, i)
                mn.approva(request.user, i, dip, int(p) if p in ('1', '2', '3', '4') else None)
                messages.success(request, f'Inviato a {dip.nome_breve}.')
            else:
                i.assegnata_a = dip
                i.save(update_fields=['assegnata_a'])
                mn.evento(i, request.user, f'Riassegnato a {dip.nome_breve}')
                mn.avvisa([dip.utente_id], request.user, f'Intervento assegnato · {i.macchina.nome}', i.descrizione, mn.url_intervento(i))
        elif azione == 'pianifica' and i.aperto and (permessi['approvatore'] or lavora):
            _quando_e_dove(request, i)
            i.save(update_fields=['da_fare_il', 'officina_esterna'])
            mn.evento(i, request.user, 'Pianificato' + (f' per il {i.da_fare_il:%d/%m}' if i.da_fare_il else '')
                      + (f' · riparazione esterna: {i.officina_esterna}' if i.officina_esterna else ''))
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
                    video = mn.controlla_video(request.FILES.get('video'))
                    mn.completa(request.user, i, lavoro, foto, ore, pezzi)
                    mn.dopo_il_lavoro(request.user, i, _collaboratori(request), (request.POST.get('resta') or '').strip()[:1000], video)
                except (ValueError, OSError):
                    messages.error(request, 'La foto o il video non sono validi (video: massimo 50 MB).')
                else:
                    messages.success(request, 'Intervento chiuso. Grazie!')
        elif azione == 'bravo' and i.stato == Intervento.Stato.COMPLETATA:
            if not i.eventi.filter(autore=request.user, testo='👍').exists():
                mn.evento(i, request.user, '👍', nota=True)
                chi = [i.completata_da_id] + [d.utente_id for d in i.collaboratori.all()]
                mn.avvisa(chi, request.user, f'👍 {mn.Intervento._nome(request.user)}', f'{i.macchina.nome}: bel lavoro!', mn.url_intervento(i))
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
        'oggi': timezone.localdate(), 'domani': timezone.localdate() + timedelta(days=1),
        'ricambi': compatibili + [r for r in Ricambio.objects.all() if r not in compatibili],
        'righe_pezzi': range(3),
        **_scelta_colleghi(request.user),
        'eventi': i.eventi.select_related('autore', 'autore__dipendente'),
        'bravi': [e.autore for e in i.eventi.filter(testo='👍').select_related('autore__dipendente')],
        'ordini': i.ordini.select_related('ricambio'),
    })


def _scelta_colleghi(utente):
    """Colleghi con cui si è lavorato: prima i manutentori (pulsanti), poi tutti gli altri (menu)."""
    io = mn.dipendente_di(utente)
    manut = [d for d in mn.manutentori() if d != io]
    altri = [d for d in Dipendente.objects.filter(attivo=True).order_by('nome') if d != io and d not in manut]
    return {'colleghi_manut': manut, 'colleghi_altri': altri}


def _collaboratori(request):
    ids = [x for x in request.POST.getlist('collaboratori') if x.isdigit()]
    return list(Dipendente.objects.filter(pk__in=ids, attivo=True))


def _quando_e_dove(request, i):
    from datetime import date

    try:
        i.da_fare_il = date.fromisoformat(request.POST.get('da_fare_il') or '')
    except ValueError:
        i.da_fare_il = None
    i.officina_esterna = (request.POST.get('officina_esterna') or '').strip()[:80]


def _pezzi_usati(request):
    pezzi = [(r, '', 1) for r in Ricambio.objects.filter(pk__in=[x for x in request.POST.getlist('pezzo_sel') if x.isdigit()])]
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
    elif tipo == 'altra':
        f = get_object_or_404(FotoIntervento, pk=oggetto_id).foto
    elif tipo == 'comunicazione':
        f = get_object_or_404(FotoComunicazione, pk=oggetto_id).foto
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
    filtro, cond = _filtro(request)
    q = (request.GET.get('q') or '').strip()
    elenco = Macchina.objects.filter(attiva=True).filter(cond())
    if q:
        elenco = elenco.filter(Q(nome__icontains=q) | Q(codice__icontains=q) | Q(categoria__icontains=q) | Q(marca__icontains=q))
    elenco = mn.stato_macchine(list(elenco))
    gruppi = [(nome, [m for m in elenco if m.luogo == v]) for v, nome in Luogo.choices]
    return render(request, 'turni/mn_macchine.html', {
        **permessi, **filtro, 'q': q, 'mostra_gruppi': not filtro['gruppo'],
        'titolo': {'macchinari': 'Lista macchinari e attrezzature', 'mezzi': 'Lista mezzi',
                   'segnaletica': 'Segnaletica e Cartelli'}.get(filtro['gruppo'], 'Macchine e mezzi'),
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
    interventi = m.interventi.select_related('assegnata_a', 'segnalata_da__dipendente', 'completata_da__dipendente').order_by('-segnalata_il')
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
        if mn.avanza_ordine(request.user, o, request.POST.get('azione'), request.POST.get('fornitore') or '', request.POST.get('dove') or ''):
            messages.success(request, f'{o.nome}: {o.get_stato_display().lower()}.')
        return redirect('turni:ordini')
    tutti = OrdineRicambio.objects.select_related('ricambio', 'macchina', 'intervento', 'richiesto_da', 'richiesto_da__dipendente', 'approvato_da__dipendente')
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
    filtro, cond = _filtro(request)
    elenco = list(Macchina.objects.filter(attiva=True).filter(cond()))
    for m in elenco:
        m.qr = qr_svg(f'{base}?macchina={m.pk}')
    return render(request, 'turni/mn_etichette.html', {'elenco': elenco, **filtro, 'mostra_gruppi': True})



CAUSE_ICONE = {'NASTRO': '➰', 'TRAMOGGIA': '🧱', 'MACCHINA': '⚙️', 'CORRENTE': '⚡', 'ALTRO': '❓'}


def _quando(valore):
    """Ora inserita a mano (datetime-local); mai nel futuro, al massimo 2 giorni fa."""
    from datetime import datetime

    adesso = timezone.now()
    try:
        d = timezone.make_aware(datetime.fromisoformat(valore)) if valore else adesso
    except (ValueError, TypeError):
        return adesso
    return min(max(d, adesso - timedelta(days=2)), adesso)


@login_required
def nuovo_fermo(request):
    impianti = dict(FermoImpianto.IMPIANTI)
    impianto = request.POST.get('impianto') or request.GET.get('impianto') or ''
    if impianto not in impianti:
        return render(request, 'turni/mn_fermo_nuovo.html', {
            'impianti': [(v, n, ICONE_LUOGHI[v], FermoImpianto.objects.filter(impianto=v, ripartito_il__isnull=True).exists())
                         for v, n in FermoImpianto.IMPIANTI],
        })
    macchine = Macchina.objects.filter(attiva=True, luogo=impianto).exclude(tipo=Macchina.Tipo.SEGNALETICA)
    if request.method == 'POST':
        causa = request.POST.get('causa')
        scelta = request.POST.get('macchina') or ''
        macchina = macchine.filter(pk=scelta).first() if scelta.isdigit() else None
        if causa not in FermoImpianto.Causa.values:
            messages.error(request, 'Scegli la causa del fermo.')
        else:
            try:
                f = mn.segnala_fermo(request.user, impianto, causa, macchina,
                                     (request.POST.get('descrizione') or '').strip()[:500],
                                     _quando(request.POST.get('dal')), request.FILES.get('foto'))
            except (ValueError, OSError):
                messages.error(request, 'La foto non è valida: riprova.')
            else:
                # fermo già finito (es. "dalle 10:05 alle 10:26"): si registra subito anche la ripartenza
                if request.POST.get('ripartito'):
                    fine = _quando(request.POST.get('ripartito'))
                    if fine > f.fermo_dal:
                        mn.fai_ripartire(request.user, f, fine, '')
                messages.success(request, 'Fermo registrato: responsabile, capo turno e manutentori sono avvisati.')
                return redirect('turni:fermo', f.pk)
    return render(request, 'turni/mn_fermo_nuovo.html', {
        'impianto': impianto, 'nome_impianto': impianti[impianto], 'macchine': macchine,
        'cause': [(v, n, CAUSE_ICONE[v]) for v, n in FermoImpianto.Causa.choices],
        'adesso': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
    })


@login_required
def fermo(request, fermo_id):
    f = get_object_or_404(FermoImpianto.objects.select_related('macchina', 'intervento', 'segnalato_da__dipendente', 'ripartenza_da__dipendente'), pk=fermo_id)
    puo = mn.puo_far_ripartire(request.user, f)
    if request.method == 'POST' and f.in_corso and puo:
        quando = _quando(request.POST.get('quando'))
        if quando < f.fermo_dal:
            messages.error(request, "L'ora di ripartenza è prima dell'inizio del fermo.")
        else:
            try:
                mn.fai_ripartire(request.user, f, quando, (request.POST.get('sistemazione') or '').strip()[:500], request.FILES.get('foto'))
            except (ValueError, OSError):
                messages.error(request, 'La foto non è valida: riprova.')
            else:
                messages.success(request, f'{f.get_impianto_display()} ripartito: fermo durato {f.durata}.')
        return redirect('turni:fermo', f.pk)
    return render(request, 'turni/mn_fermo.html', {
        'f': f, 'puo': puo, 'adesso': timezone.localtime().strftime('%Y-%m-%dT%H:%M'),
    })


@login_required
def fermi(request):
    """Storico dei fermi con le ore perse per impianto negli ultimi 30 giorni."""
    da = timezone.now() - timedelta(days=30)
    recenti = list(FermoImpianto.objects.filter(fermo_dal__gte=da).select_related('macchina', 'segnalato_da__dipendente', 'ripartenza_da__dipendente'))
    totali = []
    for v, nome in FermoImpianto.IMPIANTI:
        minuti = sum(f.minuti for f in recenti if f.impianto == v)
        totali.append((nome, sum(1 for f in recenti if f.impianto == v), f'{minuti // 60} h {minuti % 60:02d}'))
    return render(request, 'turni/mn_fermi.html', {'recenti': recenti, 'totali': totali})


@login_required
def foto_fermo(request, fermo_id, quale):
    f = get_object_or_404(FermoImpianto, pk=fermo_id)
    file = f.foto if quale == 'fermo' else f.foto_ripartenza if quale == 'ripartenza' else None
    if not file:
        raise Http404
    return FileResponse(file.open('rb'), content_type='image/jpeg')


@login_required
def comunicazioni(request):
    tutte = Comunicazione.objects.select_related('macchina', 'autore__dipendente')
    aperte = list(tutte.exclude(stato=Comunicazione.Stato.RISOLTA))
    risolte = list(tutte.filter(stato=Comunicazione.Stato.RISOLTA)[:20])
    return render(request, 'turni/mn_comunicazioni.html', {
        'aperte': aperte, 'risolte': risolte, 'puo_scrivere': mn.puo_comunicare(request.user),
    })


@login_required
def nuova_comunicazione(request):
    if not mn.puo_comunicare(request.user):
        raise PermissionDenied
    tipo = request.POST.get('tipo') or request.GET.get('tipo') or ''
    if tipo not in Comunicazione.Tipo.values:
        return render(request, 'turni/mn_comunicazione_nuova.html', {
            'tipi': [(v, n, Comunicazione.ICONE[v]) for v, n in Comunicazione.Tipo.choices],
        })
    macchine = Macchina.objects.filter(attiva=True)
    if request.method == 'POST':
        testo = (request.POST.get('testo') or '').strip()[:2000]
        scelta = request.POST.get('macchina') or ''
        macchina = macchine.filter(pk=scelta).first() if scelta.isdigit() else None
        luogo = request.POST.get('luogo') if request.POST.get('luogo') in Luogo.values else ''
        fascia = request.POST.get('fascia') if request.POST.get('fascia') in ('1T', '2T', 'N') else ''
        a = request.POST.get('destinatari') if request.POST.get('destinatari') in Comunicazione.A.values else Comunicazione.A.TUTTI
        dal = _data_ora(request.POST.get('dal'))
        al = _data_ora(request.POST.get('al'))
        motivo = request.POST.get('motivo') if request.POST.get('motivo') in Comunicazione.Motivo.values else ''
        if tipo == Comunicazione.Tipo.FERMO:
            from datetime import date

            try:
                giorno = date.fromisoformat(request.POST.get('giorno') or '')
            except ValueError:
                giorno = None
            if giorno:
                dal, al = mn.periodo_fermo(giorno, fascia)
            testo = testo or (Comunicazione.Motivo(motivo).label if motivo else '')
        if tipo == Comunicazione.Tipo.FERMO and not (luogo in dict(FermoImpianto.IMPIANTI) and motivo and dal):
            messages.error(request, "Scegli l'impianto, il motivo e il giorno del fermo.")
        elif not testo:
            messages.error(request, 'Scrivi la comunicazione.')
        elif tipo == Comunicazione.Tipo.INDISPONIBILE and not (macchina and dal and al and al > dal):
            messages.error(request, 'Indica il mezzo o la macchina e da quando a quando non è disponibile.')
        else:
            try:
                c = mn.crea_comunicazione(request.user, tipo, testo, luogo or (macchina.luogo if macchina else ''), fascia,
                                          macchina, dal, al, a, request.FILES.getlist('foto'), motivo,
                                          request.POST.get('urgente') == '1', (request.POST.get('valore') or '').strip()[:60],
                                          mn.controlla_video(request.FILES.get('video')))
            except (ValueError, OSError):
                messages.error(request, 'Una delle foto o il video non sono validi (video: massimo 50 MB).')
            else:
                messages.success(request, 'Comunicazione inviata.')
                return redirect('turni:comunicazione', c.pk)
    gruppi = [(nome, [m for m in macchine if m.luogo == v]) for v, nome in Luogo.choices]
    return render(request, 'turni/mn_comunicazione_nuova.html', {
        'tipo': tipo, 'nome_tipo': Comunicazione.Tipo(tipo).label, 'icona': Comunicazione.ICONE[tipo],
        'gruppi': [g for g in gruppi if g[1]], 'luoghi': Luogo.choices,
        'destinatari': Comunicazione.A.choices,
        'predefinito': Comunicazione.A.PALISTI if tipo == Comunicazione.Tipo.INDISPONIBILE else Comunicazione.A.TUTTI,
        'impianti': [(v, n, ICONE_LUOGHI[v]) for v, n in FermoImpianto.IMPIANTI], 'motivi': Comunicazione.Motivo.choices,
        'domani': (timezone.localdate() + timedelta(days=1)).isoformat(),
    })


def _data_ora(valore):
    from datetime import datetime

    try:
        return timezone.make_aware(datetime.fromisoformat(valore)) if valore else None
    except (ValueError, TypeError):
        return None


@login_required
def comunicazione(request, comunicazione_id):
    c = get_object_or_404(Comunicazione.objects.select_related('macchina', 'autore__dipendente', 'in_gestione_da__dipendente', 'risolta_da__dipendente'), pk=comunicazione_id)
    if request.method == 'POST':
        mn.rispondi(request.user, c, (request.POST.get('testo') or '').strip(), request.POST.get('azione'))
        return redirect('turni:comunicazione', c.pk)
    return render(request, 'turni/mn_comunicazione.html', {
        'c': c, 'risposte': c.risposte.select_related('autore__dipendente'), 'puo_chiudere': mn.puo_chiudere(request.user, c),
        'in_gestione_nome': Intervento._nome(c.in_gestione_da), 'risolta_nome': Intervento._nome(c.risolta_da),
    })


@login_required
def video(request, tipo, oggetto_id):
    import mimetypes
    import re

    from django.http import HttpResponse

    if tipo == 'intervento':
        f = get_object_or_404(Intervento, pk=oggetto_id).video
    elif tipo == 'comunicazione':
        f = get_object_or_404(Comunicazione, pk=oggetto_id).video
    else:
        raise Http404
    if not f:
        raise Http404
    tipo_mime = mimetypes.guess_type(f.name)[0] or 'video/mp4'
    dimensione = f.size
    intervallo = re.match(r'bytes=(\d+)-(\d*)', request.headers.get('Range', ''))
    if not intervallo:
        r = FileResponse(f.open('rb'), content_type=tipo_mime)
        r['Accept-Ranges'] = 'bytes'
        return r
    inizio = int(intervallo.group(1))
    fine = min(int(intervallo.group(2)) if intervallo.group(2) else dimensione - 1, dimensione - 1)
    if inizio > fine:
        return HttpResponse(status=416, headers={'Content-Range': f'bytes */{dimensione}'})
    with f.open('rb') as file:
        file.seek(inizio)
        dati = file.read(fine - inizio + 1)
    r = HttpResponse(dati, status=206, content_type=tipo_mime)
    r['Content-Range'] = f'bytes {inizio}-{fine}/{dimensione}'
    r['Accept-Ranges'] = 'bytes'
    return r


@login_required
def ripartenza(request):
    """Un solo impianto fermo: si va dritti alla ripartenza. Più di uno: si sceglie quale."""
    in_corso = list(FermoImpianto.objects.filter(ripartito_il__isnull=True).select_related('macchina').order_by('fermo_dal'))
    if len(in_corso) == 1:
        return redirect(reverse('turni:fermo', args=[in_corso[0].pk]) + '#riparti')
    return render(request, 'turni/mn_ripartenza.html', {'in_corso': in_corso})
