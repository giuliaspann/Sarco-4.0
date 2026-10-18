import secrets
from datetime import date, timedelta
from itertools import groupby

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from . import importa
from .forms import AccessoForm, ImportaForm
from .models import Dipendente, ElementoPulizia, Fascia, FASCE_LAVORATIVE, Pulizia, Settimana, Turno
from .pulizie import genera_pulizie, mezzi_aggiungibili, salva_foto, turno_attuale
from .richieste import extra_per
from .views_messaggi import non_letti_bacheca, non_letti_chat

ORDINE_FASCE = [Fascia.MATTINA, Fascia.GIORNALIERO, Fascia.POMERIGGIO, Fascia.NOTTE, Fascia.ALTRO]


class Accesso(LoginView):
    form_class = AccessoForm
    template_name = 'turni/login.html'
    redirect_authenticated_user = True


def dipendente_di(request):
    return getattr(request.user, 'dipendente', None)


def e_capoturno(user, giorno):
    if user.is_staff:
        return True
    dip = getattr(user, 'dipendente', None)
    return bool(dip) and dip.turni.filter(data__in=[giorno, giorno - timedelta(days=1)], capoturno=True).exists()


def leggi_data(valore, predefinita):
    try:
        return date.fromisoformat(valore)
    except (TypeError, ValueError):
        return predefinita


@login_required
def home(request):
    """Per l'operaio: pagina di scorciatoie (un pulsante grande per ogni cosa che può fare)."""
    dip = dipendente_di(request)
    if dip is None:
        from .richieste import e_responsabile

        if e_responsabile(request.user):
            return redirect('turni:ufficio_richieste')
        if request.user.is_staff:
            return redirect('turni:importa')
        return redirect('turni:miei_turni')

    turno = turno_attuale(dip)
    pulizie_da_fare = None
    if turno and turno.lavora:
        genera_pulizie(turno)
        pulizie_da_fare = turno.pulizie.exclude(stato__in=[Pulizia.Stato.FATTA, Pulizia.Stato.VERIFICATA]).count()
    domani = timezone.localdate() + timedelta(days=1)
    return render(
        request,
        'turni/home.html',
        {
            'dip': dip,
            'oggi': timezone.localdate(),
            'turno': turno,
            'domani': dip.turni.filter(data=domani, settimana__pubblicata=True).first(),
            'pulizie_da_fare': pulizie_da_fare,
            'extra': [e for e in extra_per(dip) if not e.mia],
            'bacheca_nuovi': non_letti_bacheca(request.user),
            'chat_nuovi': non_letti_chat(request.user),
            # pulizie segnate "fatte" che aspettano il controllo del capo turno
            'da_verificare': Pulizia.objects.filter(turno__data=timezone.localdate(), stato=Pulizia.Stato.FATTA).count()
            if e_capoturno(request.user, timezone.localdate())
            else 0,
        },
    )


@login_required
def miei_turni(request):
    """Calendario di due settimane (come il file settimanale, più la successiva):
    una sigla colorata per giorno, sotto il dettaglio del giorno scelto."""
    dip = dipendente_di(request)
    if dip is None:
        return render(request, 'turni/nessun_dipendente.html')
    oggi = timezone.localdate()
    giorno = leggi_data(request.GET.get('giorno'), None)
    base = leggi_data(request.GET.get('settimana'), giorno or oggi)
    inizio = base - timedelta(days=base.weekday())
    fine = inizio + timedelta(days=13)
    if giorno and inizio <= giorno <= fine:
        scelto = giorno
    else:
        scelto = oggi if inizio <= oggi <= fine else inizio

    turni = {t.data: t for t in dip.turni.filter(data__range=(inizio, fine), settimana__pubblicata=True)}
    lunedi_oggi = oggi - timedelta(days=oggi.weekday())
    settimane = []
    for lun in (inizio, inizio + timedelta(days=7)):
        distanza = (lun - lunedi_oggi).days // 7
        nome = {0: 'Questa settimana', 1: 'Prossima settimana', -1: 'Settimana scorsa'}.get(
            distanza, f'Dal {lun:%d/%m}'
        )
        giorni = [{'data': lun + timedelta(days=i), 'turno': turni.get(lun + timedelta(days=i))} for i in range(7)]
        settimane.append({'nome': nome, 'giorni': giorni, 'caricata': any(c['turno'] for c in giorni)})

    turno = turni.get(scelto)
    colleghi = []
    if turno and turno.lavora:
        colleghi = (
            Turno.objects.filter(data=scelto, fascia=turno.fascia, postazione=turno.postazione)
            .exclude(dipendente=dip)
            .select_related('dipendente')
            .order_by('dipendente__nome')
        )
    note = [
        n
        for s in Settimana.objects.filter(lunedi__range=(inizio, fine), pubblicata=True).prefetch_related('note')
        for n in s.note.all()
        if importa.stesso_nome(n.dipendente, dip.nome)
    ]
    return render(
        request,
        'turni/miei_turni.html',
        {
            'dip': dip,
            'inizio': inizio,
            'fine': fine,
            'settimane': settimane,
            'oggi': oggi,
            'scelto': scelto,
            'turno': turno,
            'colleghi': colleghi,
            'note': note,
            'prec': inizio - timedelta(days=7),
            'succ': inizio + timedelta(days=7),
            'extra': extra_per(dip),
        },
    )


@login_required
def squadra(request):
    oggi = timezone.localdate()
    giorno = leggi_data(request.GET.get('giorno'), oggi)
    turni = list(
        Turno.objects.filter(data=giorno, settimana__pubblicata=True)
        .select_related('dipendente')
        .order_by('dipendente__nome')
    )
    lavorano = [t for t in turni if t.lavora]
    gruppi = []
    # i capi turno senza fascia scritta vanno in cima
    for fascia in [Fascia.ALTRO] + ORDINE_FASCE[:-1]:
        della_fascia = sorted(
            (t for t in lavorano if t.fascia == fascia), key=lambda t: (t.postazione == '', t.postazione, not t.capoturno)
        )
        if della_fascia:
            sottogruppi = [
                (k, list(v)) for k, v in groupby(della_fascia, key=lambda t: t.get_postazione_display() or 'Senza postazione')
            ]
            gruppi.append((Fascia(fascia).label if fascia != Fascia.ALTRO else 'Capi turno', sottogruppi))
    assenti = [t for t in turni if not t.lavora]
    return render(
        request,
        'turni/squadra.html',
        {
            'giorno': giorno,
            'oggi': giorno == oggi,
            'gruppi': gruppi,
            'assenti': assenti,
            'prec': giorno - timedelta(days=1),
            'succ': giorno + timedelta(days=1),
            'mio': dipendente_di(request),
        },
    )


# ---------------------------------------------------------------- pulizie


@login_required
def pulizie(request, turno_id=None):
    dip = dipendente_di(request)
    if dip is None:
        return render(request, 'turni/nessun_dipendente.html')
    if turno_id is None:
        turno = turno_attuale(dip)
    else:
        turno = get_object_or_404(Turno, pk=turno_id, dipendente=dip)
    oggi = timezone.localdate()
    recenti = dip.turni.filter(data__range=(oggi - timedelta(days=2), oggi), fascia__in=FASCE_LAVORATIVE).order_by('-data')

    if turno is None or not turno.lavora:
        return render(request, 'turni/pulizie.html', {'turno': turno, 'recenti': recenti})

    if request.method == 'POST':
        azione = request.POST.get('azione')
        if azione == 'aggiungi':
            elemento = get_object_or_404(mezzi_aggiungibili(turno), pk=request.POST.get('elemento'))
            Pulizia.objects.get_or_create(turno=turno, elemento=elemento, defaults={'aggiunta_da_operaio': True})
        else:
            p = get_object_or_404(turno.pulizie, pk=request.POST.get('pulizia'))
            if p.stato == Pulizia.Stato.VERIFICATA:
                messages.info(request, 'Questa pulizia è già stata verificata.')
            elif azione == 'rimuovi' and p.aggiunta_da_operaio and p.stato == Pulizia.Stato.DA_FARE:
                p.delete()
            elif azione == 'fatta':
                if request.FILES.get('foto'):
                    try:
                        salva_foto(p, request.FILES['foto'])
                    except Exception:
                        messages.error(request, 'La foto non si legge: riprova a scattarla.')
                        return redirect('turni:pulizie_turno', turno.pk)
                p.nota = request.POST.get('nota', '')[:300]
                p.stato = Pulizia.Stato.FATTA
                p.fatta_il = timezone.now()
                p.save()
        return redirect('turni:pulizie_turno', turno.pk)

    genera_pulizie(turno)
    voci = list(turno.pulizie.select_related('elemento'))
    return render(
        request,
        'turni/pulizie.html',
        {
            'turno': turno,
            'voci': voci,
            'fatte': sum(v.stato in (Pulizia.Stato.FATTA, Pulizia.Stato.VERIFICATA) for v in voci),
            'mezzi': mezzi_aggiungibili(turno),
            'recenti': recenti,
        },
    )


@login_required
def capoturno(request):
    oggi = timezone.localdate()
    giorno = leggi_data(request.GET.get('giorno'), oggi)
    if not e_capoturno(request.user, giorno):
        raise PermissionDenied

    if request.method == 'POST':
        p = get_object_or_404(Pulizia, pk=request.POST.get('pulizia'), turno__data=giorno)
        if p.turno.dipendente.utente_id == request.user.pk and not request.user.is_staff:
            messages.error(request, 'Le tue pulizie le verifica un altro capo turno.')
        else:
            ok = request.POST.get('azione') == 'verifica'
            p.stato = Pulizia.Stato.VERIFICATA if ok else Pulizia.Stato.SEGNALATA
            p.verificata_da = request.user
            p.verificata_il = timezone.now()
            p.nota_verifica = request.POST.get('nota', '')[:300]
            p.save()
        return redirect(f"{request.path}?giorno={giorno.isoformat()}#d{p.turno_id}")

    del_giorno = Turno.objects.filter(data=giorno, fascia__in=FASCE_LAVORATIVE)
    for t in del_giorno:
        genera_pulizie(t)
    turni = list(
        del_giorno.select_related('dipendente')
        .prefetch_related('pulizie__elemento')
        .annotate(
            n_voci=Count('pulizie'),
            n_fatte=Count('pulizie', filter=Q(pulizie__stato__in=[Pulizia.Stato.FATTA, Pulizia.Stato.VERIFICATA])),
            n_da_verificare=Count('pulizie', filter=Q(pulizie__stato=Pulizia.Stato.FATTA)),
        )
    )
    fascia = request.GET.get('fascia', '')
    if fascia:
        turni = [t for t in turni if t.fascia == fascia]
    turni.sort(key=lambda t: (-t.n_da_verificare, ORDINE_FASCE.index(t.fascia), t.dipendente.nome))
    from .models import AvvisoAssenza

    return render(
        request,
        'turni/capoturno.html',
        {
            'avvisi': AvvisoAssenza.objects.filter(data=giorno).select_related('dipendente'),
            'giorno': giorno,
            'turni': turni,
            'fascia': fascia,
            # sigle come nel calendario, così la barra sta su una riga
            'fasce': [(f, Turno.SIGLE[f]) for f in (Fascia.MATTINA, Fascia.POMERIGGIO, Fascia.NOTTE, Fascia.GIORNALIERO)],
            'prec': giorno - timedelta(days=1),
            'succ': giorno + timedelta(days=1),
        },
    )


@login_required
def foto(request, pulizia_id):
    p = get_object_or_404(Pulizia.objects.select_related('turno__dipendente'), pk=pulizia_id)
    proprietario = p.turno.dipendente.utente_id == request.user.pk
    if not (proprietario or e_capoturno(request.user, p.turno.data)):
        raise PermissionDenied
    if not p.foto:
        raise Http404
    return FileResponse(p.foto.open('rb'), content_type='image/jpeg')


# ---------------------------------------------------------------- ufficio


@staff_member_required
def importa_turni(request):
    if request.method == 'POST':
        form = ImportaForm(request.POST, request.FILES)
        if form.is_valid():
            f = form.cleaned_data['file']
            lunedi = form.cleaned_data['lunedi'] or importa.lunedi_da_nome_file(f.name)
            if lunedi is None:
                form.add_error('lunedi', 'Dal nome del file non capisco la settimana: indica il lunedì.')
            else:
                lunedi -= timedelta(days=lunedi.weekday())
                try:
                    letta = importa.leggi_file(f, lunedi)
                except Exception as e:
                    form.add_error('file', f'Non riesco a leggere il file: {e}')
                else:
                    request.session['import_turni'] = importa.in_sessione(letta)
                    request.session['import_nome_file'] = f.name
                    return redirect('turni:anteprima')
    else:
        form = ImportaForm()
    settimane = Settimana.objects.annotate(n=Count('turni__dipendente', distinct=True))[:8]
    return render(request, 'turni/ufficio_importa.html', {'form': form, 'settimane': settimane})


@staff_member_required
def anteprima(request):
    dati = request.session.get('import_turni')
    if not dati:
        return redirect('turni:importa')
    letta = importa.da_sessione(dati)
    if request.method == 'POST':
        settimana, nuovi, mantenuti = importa.salva_settimana(
            letta, request.user, request.session.get('import_nome_file', '')
        )
        del request.session['import_turni']
        messages.success(request, f'Turni caricati: {settimana}.')
        if nuovi:
            messages.info(request, f'Nuovi dipendenti: {", ".join(nuovi)}. Ricorda di creare il loro PIN.')
        if mantenuti:
            messages.warning(
                request, "Tenuti i cambi e le ferie approvati nell'app, diversi dal file: " + '; '.join(mantenuti)
            )
        return redirect('turni:importa')

    esistenti = list(Dipendente.objects.all())
    righe = []
    for r in letta.righe:
        trovato = importa.trova_dipendente(r.nome, esistenti)
        turni = []
        for c in r.turni:
            t = Turno(fascia=c.fascia, postazione=c.postazione, capoturno=c.capoturno, codice=c.codice)
            turni.append(t)
        righe.append({'nome': r.nome, 'nuovo': trovato is None, 'come': trovato.nome if trovato and trovato.nome != r.nome else '', 'turni': turni})
    giorni = [letta.lunedi + timedelta(days=i) for i in range(7)]
    return render(
        request,
        'turni/ufficio_anteprima.html',
        {
            'letta': letta,
            'righe': righe,
            'giorni': giorni,
            'domenica': giorni[-1],
            'esiste': Settimana.objects.filter(lunedi=letta.lunedi).exists(),
        },
    )


def nome_utente_per(dip):
    parole = [p for p in slugify(dip.nome.replace("'", ' ')).split('-') if len(p) > 1]
    base = '.'.join(parole[:2]) or f'dip{dip.pk}'
    nome, i = base, 2
    User = get_user_model()
    while User.objects.filter(username=nome).exclude(dipendente=dip).exists():
        nome, i = f'{base}{i}', i + 1
    return nome


@staff_member_required
def dipendenti(request):
    if request.method == 'POST':
        dip = get_object_or_404(Dipendente, pk=request.POST.get('dipendente'))
        azione = request.POST.get('azione')
        if azione == 'pin':
            pin = f'{secrets.randbelow(10**6):06d}'
            utente = dip.utente
            if utente is None:
                utente = get_user_model().objects.create_user(nome_utente_per(dip), first_name=dip.nome_breve)
                dip.utente = utente
            utente.set_password(pin)
            utente.is_active = True
            utente.save()
            dip.tentativi_falliti, dip.bloccato_fino = 0, None
            dip.save()
            messages.success(
                request,
                f'{dip.nome_breve} — nome utente: {utente.username} — PIN: {pin}. '
                'Annotalo e comunicalo alla persona: non verrà più mostrato.',
            )
        elif azione == 'attivo':
            dip.attivo = not dip.attivo
            dip.save(update_fields=['attivo'])
            if dip.utente:
                dip.utente.is_active = dip.attivo
                dip.utente.save(update_fields=['is_active'])
        return redirect('turni:dipendenti')
    elenco = Dipendente.objects.select_related('utente').order_by('-attivo', 'nome')
    return render(request, 'turni/ufficio_dipendenti.html', {'elenco': elenco})


# ---------------------------------------------------------------- app installabile


def manifest(request):
    from django.http import JsonResponse
    from django.templatetags.static import static

    return JsonResponse(
        {
            'name': 'Sarco Turni',
            'short_name': 'Turni',
            'start_url': '/turni/',
            'scope': '/',
            'display': 'standalone',
            'background_color': '#f4f5f2',
            'theme_color': '#1f5f3f',
            'icons': [
                {'src': static('turni/icona-192.png'), 'sizes': '192x192', 'type': 'image/png'},
                {'src': static('turni/icona-512.png'), 'sizes': '512x512', 'type': 'image/png'},
            ],
        },
        content_type='application/manifest+json',
    )


SERVICE_WORKER = """
// Rende l'app installabile, mostra un avviso senza rete e le notifiche push.
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => self.clients.claim());
self.addEventListener('push', e => {
  let d = {};
  try { d = e.data.json(); } catch (err) { d = { titolo: 'Sarco Turni', testo: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(d.titolo || 'Sarco Turni', {
    body: d.testo || '', icon: '/static/turni/icona-192.png', badge: '/static/turni/icona-192.png',
    data: { url: d.url || '/turni/' },
  }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/turni/';
  e.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(finestre => {
    for (const f of finestre) { if ('focus' in f) { f.navigate(url); return f.focus(); } }
    return clients.openWindow(url);
  }));
});
self.addEventListener('fetch', e => {
  if (e.request.mode !== 'navigate') return;
  e.respondWith(fetch(e.request).catch(() => new Response(
    '<meta name=viewport content="width=device-width"><body style="font-family:sans-serif;padding:2rem">'
    + '<h2>Nessuna connessione</h2><p>Riprova quando torna la rete.</p>',
    {headers: {'Content-Type': 'text/html; charset=utf-8'}})));
});
"""


def service_worker(request):
    return HttpResponse(SERVICE_WORKER, content_type='application/javascript')
