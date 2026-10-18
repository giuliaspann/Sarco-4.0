from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import richieste as svc
from .models import AvvisoAssenza, CambioTurno, Dipendente, Disponibilita, Postazione, RichiestaFerie, Turno, TurnoExtra
from .views import dipendente_di

# Il giorno di recupero si cerca entro due settimane dal giorno del cambio
FINESTRA_RECUPERO = 14


def _data(valore):
    try:
        return date.fromisoformat(valore)
    except (TypeError, ValueError):
        return None


def _serve_dipendente(request):
    dip = dipendente_di(request)
    if dip is None:
        raise PermissionDenied
    return dip


@login_required
def richieste(request):
    dip = _serve_dipendente(request)
    if request.method == 'POST':
        azione = request.POST.get('azione')
        try:
            if azione in ('accetta', 'rifiuta'):
                cambio = get_object_or_404(CambioTurno, pk=request.POST.get('cambio'), collega=dip)
                svc.risposta_collega(cambio, azione == 'accetta')
                messages.success(
                    request,
                    'Cambio accettato: ora deve approvarlo l\'ufficio.' if azione == 'accetta' else 'Cambio rifiutato.',
                )
            elif azione == 'annulla_cambio':
                cambio = get_object_or_404(
                    CambioTurno, pk=request.POST.get('cambio'), richiedente=dip, stato__in=CambioTurno.IN_CORSO
                )
                cambio.stato = CambioTurno.Stato.ANNULLATO
                cambio.save()
            elif azione == 'annulla_ferie':
                f = get_object_or_404(
                    RichiestaFerie, pk=request.POST.get('ferie'), dipendente=dip, stato=RichiestaFerie.Stato.ATTESA
                )
                f.stato = RichiestaFerie.Stato.ANNULLATA
                f.save()
        except svc.RichiestaNonValida as e:
            messages.error(request, str(e))
        return redirect('turni:richieste')

    da_rispondere = [
        c
        for c in CambioTurno.objects.filter(collega=dip, stato=CambioTurno.Stato.ATTESA_COLLEGA).select_related(
            'richiedente'
        )
        if not c.scaduto
    ]
    for c in da_rispondere:
        c.righe = _righe_cambio(c, dip)
    cambi = list(
        CambioTurno.objects.filter(Q(richiedente=dip) | Q(collega=dip))
        .exclude(pk__in=[c.pk for c in da_rispondere])
        .select_related('richiedente', 'collega')[:20]
    )
    for c in cambi:
        c.altro = c.collega if c.richiedente_id == dip.pk else c.richiedente
        c.mio = c.richiedente_id == dip.pk
    return render(
        request,
        'turni/richieste.html',
        {
            'da_rispondere': da_rispondere,
            'cambi': cambi,
            'ferie': dip.richieste_ferie.all()[:20],
            'avvisi': dip.avvisi.all()[:10],
        },
    )


def _righe_cambio(cambio, punto_di_vista):
    """Per ogni giorno: il mio turno ora e dopo il cambio (dal punto di vista di chi guarda)."""
    altro = cambio.collega if punto_di_vista.pk == cambio.richiedente_id else cambio.richiedente
    turni = svc.turni_coinvolti(cambio.richiedente, cambio.collega, cambio.giorni)
    righe = []
    for g in cambio.giorni:
        io, lui = turni.get((punto_di_vista.pk, g)), turni.get((altro.pk, g))
        if io and lui:
            righe.append({'giorno': g, 'prima': io, 'dopo': lui})
    return righe


@login_required
def nuovo_cambio(request):
    dip = _serve_dipendente(request)
    oggi = timezone.localdate()
    giorno = _data(request.GET.get('giorno') or request.POST.get('giorno'))
    collega = None
    if request.GET.get('collega') or request.POST.get('collega'):
        collega = get_object_or_404(
            Dipendente, pk=request.GET.get('collega') or request.POST.get('collega'), attivo=True
        )

    if request.method == 'POST':
        try:
            cambio = svc.crea_cambio(
                dip, collega, giorno, _data(request.POST.get('giorno2')), request.POST.get('motivo', '')
            )
        except svc.RichiestaNonValida as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f'Richiesta inviata a {cambio.collega.nome_breve}.')
            return redirect('turni:richieste')

    contesto = {'giorno': giorno, 'collega': collega}

    if giorno is None or giorno <= oggi:
        # 1. scelta del giorno
        contesto['miei'] = dip.turni.filter(data__gt=oggi, settimana__pubblicata=True).order_by('data')[:21]
        return render(request, 'turni/cambio_nuovo.html', contesto)

    mio = get_object_or_404(Turno, dipendente=dip, data=giorno, settimana__pubblicata=True)
    contesto['mio'] = mio

    if collega is None:
        # 2. scelta del collega: prima chi ha la mia stessa postazione
        altri = (
            Turno.objects.filter(data=giorno, dipendente__attivo=True)
            .exclude(dipendente=dip)
            .select_related('dipendente', 'dipendente__utente')
        )
        stessa, resto = [], []
        for t in altri:
            if (t.fascia, t.postazione, t.capoturno) == (mio.fascia, mio.postazione, mio.capoturno):
                continue  # stesso turno: non c'è niente da scambiare quel giorno
            (stessa if mio.postazione and t.postazione == mio.postazione else resto).append(t)
        contesto.update({'stessa': stessa, 'resto': sorted(resto, key=lambda t: t.dipendente.nome)})
        return render(request, 'turni/cambio_nuovo.html', contesto)

    # 3. giorno di recupero facoltativo e conferma
    suo = get_object_or_404(Turno, dipendente=collega, data=giorno)
    da, a = max(oggi + timedelta(days=1), giorno - timedelta(days=FINESTRA_RECUPERO)), giorno + timedelta(
        days=FINESTRA_RECUPERO
    )
    miei = {t.data: t for t in dip.turni.filter(data__range=(da, a), settimana__pubblicata=True)}
    suoi = {t.data: t for t in collega.turni.filter(data__range=(da, a), settimana__pubblicata=True)}
    recuperi = []
    # il recupero ha senso solo per "lavoro contro riposo"; tra due turni di lavoro basta un giorno
    for g in sorted(miei) if mio.lavora != suo.lavora else []:
        if g == giorno or g not in suoi:
            continue
        m, s = miei[g], suoi[g]
        # proposto solo se l'opposto del giorno del cambio: uno lavora e l'altro no
        if m.lavora != s.lavora and m.lavora != mio.lavora:
            recuperi.append({'giorno': g, 'mio': m, 'suo': s})
    contesto.update({'suo': suo, 'recuperi': recuperi, 'senza_account': collega.utente_id is None})
    return render(request, 'turni/cambio_nuovo.html', contesto)


@login_required
def nuove_ferie(request):
    dip = _serve_dipendente(request)
    if request.method == 'POST':
        dal, al = _data(request.POST.get('dal')), _data(request.POST.get('al'))
        tipo = request.POST.get('tipo')
        if not dal or not al or tipo not in RichiestaFerie.Tipo.values:
            messages.error(request, 'Indica tipo, data di inizio e di fine.')
        else:
            try:
                svc.crea_ferie(dip, tipo, dal, al, request.POST.get('motivo', ''))
            except svc.RichiestaNonValida as e:
                messages.error(request, str(e))
            else:
                messages.success(request, 'Richiesta inviata all\'ufficio.')
                return redirect('turni:richieste')
    return render(
        request,
        'turni/ferie_nuove.html',
        {'tipi': RichiestaFerie.Tipo.choices, 'domani': timezone.localdate() + timedelta(days=1), 'dati': request.POST},
    )


# ---------------------------------------------------------------- ufficio


@login_required
def ufficio_richieste(request):
    if not svc.e_responsabile(request.user):
        raise PermissionDenied
    if request.method == 'POST':
        approva = request.POST.get('azione') == 'approva'
        nota = request.POST.get('nota', '')
        try:
            if request.POST.get('avviso'):
                a = get_object_or_404(AvvisoAssenza, pk=request.POST['avviso'])
                a.visto_da, a.visto_il = request.user, timezone.now()
                a.save(update_fields=['visto_da', 'visto_il'])
            elif request.POST.get('cambio'):
                c = get_object_or_404(CambioTurno, pk=request.POST['cambio'])
                svc.decisione_ufficio_cambio(c, request.user, approva, nota)
                messages.success(request, f'Cambio {c.richiedente.nome_breve} ↔ {c.collega.nome_breve} {"approvato" if approva else "rifiutato"}.')
            else:
                f = get_object_or_404(RichiestaFerie, pk=request.POST.get('ferie'))
                svc.decisione_ufficio_ferie(f, request.user, approva, nota)
                messages.success(request, f'{f.get_tipo_display()} di {f.dipendente.nome_breve} {"approvate" if approva else "rifiutate"}.')
        except svc.RichiestaNonValida as e:
            messages.error(request, str(e))
        return redirect('turni:ufficio_richieste')

    cambi = list(
        CambioTurno.objects.filter(stato=CambioTurno.Stato.ATTESA_UFFICIO).select_related('richiedente', 'collega')
    )
    for c in cambi:
        c.righe = _righe_cambio(c, c.richiedente)
    ferie = list(RichiestaFerie.objects.filter(stato=RichiestaFerie.Stato.ATTESA).select_related('dipendente'))
    for f in ferie:
        turni = f.dipendente.turni.filter(data__range=(f.dal, f.al))
        f.turni_lavoro = [t for t in turni if t.lavora]
        f.non_caricati = f.giorni - turni.count()
        f.colleghi_assenti = (
            RichiestaFerie.objects.filter(stato=RichiestaFerie.Stato.APPROVATA, dal__lte=f.al, al__gte=f.dal)
            .exclude(dipendente=f.dipendente)
            .select_related('dipendente')
        )
    storico_cambi = CambioTurno.objects.exclude(stato__in=CambioTurno.IN_CORSO).select_related('richiedente', 'collega')[:15]
    storico_ferie = RichiestaFerie.objects.exclude(stato=RichiestaFerie.Stato.ATTESA).select_related('dipendente')[:15]
    in_attesa_collega = CambioTurno.objects.filter(stato=CambioTurno.Stato.ATTESA_COLLEGA).count()
    avvisi = AvvisoAssenza.objects.filter(
        Q(visto_il__isnull=True) | Q(data__gte=timezone.localdate() - timedelta(days=2))
    ).select_related('dipendente', 'visto_da')
    return render(
        request,
        'turni/ufficio_richieste.html',
        {
            'avvisi': avvisi,
            'cambi': cambi,
            'ferie': ferie,
            'storico_cambi': storico_cambi,
            'storico_ferie': storico_ferie,
            'in_attesa_collega': in_attesa_collega,
        },
    )


# ---------------------------------------------------------------- turni extra e avvisi


@login_required
@require_POST
def rispondi_extra(request, extra_id):
    dip = _serve_dipendente(request)
    extra = get_object_or_404(TurnoExtra, pk=extra_id)
    try:
        if request.POST.get('azione') == 'ritira':
            svc.ritira(extra, dip)
            messages.info(request, 'Disponibilità ritirata.')
        else:
            svc.offri(extra, dip)
            messages.success(request, "Grazie! L'ufficio ti farà sapere se servi.")
    except svc.RichiestaNonValida as e:
        messages.error(request, str(e))
    return redirect('turni:miei_turni')


@login_required
def nuovo_avviso(request):
    dip = _serve_dipendente(request)
    oggi = timezone.localdate()
    if request.method == 'POST':
        giorno = _data(request.POST.get('data')) or oggi
        tipo = request.POST.get('tipo')
        if tipo not in AvvisoAssenza.Tipo.values:
            messages.error(request, 'Scegli il tipo di avviso.')
        elif abs((giorno - oggi).days) > 30:
            messages.error(request, 'La data è troppo lontana.')
        else:
            AvvisoAssenza.objects.create(dipendente=dip, data=giorno, tipo=tipo, nota=request.POST.get('nota', '')[:300])
            messages.success(request, "Avviso inviato all'ufficio e al capo turno.")
            return redirect('turni:richieste')
    return render(
        request, 'turni/avviso_nuovo.html', {'tipi': AvvisoAssenza.Tipo.choices, 'oggi': oggi, 'dati': request.POST}
    )


@login_required
def ufficio_extra(request):
    if not svc.e_responsabile(request.user):
        raise PermissionDenied
    oggi = timezone.localdate()
    if request.method == 'POST':
        azione = request.POST.get('azione')
        try:
            if azione == 'crea':
                giorno = _data(request.POST.get('data'))
                fascia = request.POST.get('fascia')
                if not giorno or giorno < oggi or fascia not in dict(TurnoExtra._meta.get_field('fascia').choices):
                    raise svc.RichiestaNonValida('Indica un giorno da oggi in poi e il turno.')
                posti = max(1, min(20, int(request.POST.get('posti') or 1)))
                postazione = request.POST.get('postazione', '')
                if postazione not in Postazione.values:
                    postazione = ''
                TurnoExtra.objects.create(
                    data=giorno, fascia=fascia, postazione=postazione, posti=posti,
                    nota=request.POST.get('nota', '')[:300], creata_da=request.user,
                )
                messages.success(request, 'Richiesta pubblicata: gli operai liberi quel giorno la vedono nei Turni.')
            elif azione == 'conferma':
                disp = get_object_or_404(Disponibilita, pk=request.POST.get('disponibilita'))
                svc.conferma_volontario(disp)
                messages.success(request, f'{disp.dipendente.nome_breve} confermato: il turno è nel suo calendario.')
            elif azione in ('chiudi', 'riapri'):
                extra = get_object_or_404(TurnoExtra, pk=request.POST.get('extra'))
                extra.chiusa = azione == 'chiudi'
                extra.save(update_fields=['chiusa'])
        except (svc.RichiestaNonValida, ValueError) as e:
            messages.error(request, str(e) or 'Dati non validi.')
        return redirect('turni:ufficio_extra')

    aperte = TurnoExtra.objects.filter(data__gte=oggi).prefetch_related('disponibilita__dipendente')
    return render(
        request,
        'turni/ufficio_extra.html',
        {
            'aperte': aperte,
            'fasce': TurnoExtra._meta.get_field('fascia').choices,
            'postazioni': Postazione.choices,
            'oggi': oggi,
        },
    )
