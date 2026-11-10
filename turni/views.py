from datetime import date, timedelta
from itertools import groupby
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from . import accessi, importa, saldi
from .forms import AccessoForm, ImportaForm
from .models import Dipendente, ElementoPulizia, Fascia, FASCE_LAVORATIVE, Postazione, Pulizia, Settimana, Turno
from .pulizie import (ORA_NOTTE, promemoria_di, aggiungibili, capi_della_notte, da_convalidare_piazzale, e_resp_piazzale, elemento_da_scelta,
                      genera_pulizie, in_turno_oggi, mezzi_aggiungibili, passa_pulizia, pulizia_generale_in_attesa, resp_piazzale,
                      richiedi_pulizia, salva_foto, scelte_pulizia, turno_attuale)
from .pulizie import squadra as squadra_del_capo  # "squadra" è già la pagina «Con chi lavoro oggi»
from .richieste import extra_per
from .views_messaggi import non_letti_bacheca, non_letti_chat

ORDINE_FASCE = [Fascia.MATTINA, Fascia.GIORNALIERO, Fascia.POMERIGGIO, Fascia.NOTTE, Fascia.ALTRO]


class Accesso(LoginView):
    form_class = AccessoForm
    template_name = 'turni/login.html'
    redirect_authenticated_user = True

    def get_initial(self):
        iniziali = super().get_initial()
        if self.request.GET.get('u'):
            iniziali['username'] = self.request.GET['u'][:150]
        return iniziali


def dipendente_di(request):
    return getattr(request.user, 'dipendente', None)


def e_capoturno(user, giorno):
    if user.is_staff:
        return True
    dip = getattr(user, 'dipendente', None)
    return bool(dip) and dip.turni.filter(data__in=[giorno, giorno - timedelta(days=1)], capoturno=True).exists()


def fasce_del_capo(user, giorno):
    """I turni in cui la persona è Capo Turno quel giorno: verifica solo le pulizie di quei turni.
    None = l'ufficio, che le vede tutte."""
    dip = getattr(user, 'dipendente', None)
    fasce = set()
    if dip:
        for f in dip.turni.filter(data=giorno, capoturno=True).values_list('fascia', flat=True):
            fasce.add(Fascia.MATTINA if f == Fascia.ALTRO else f)  # Capo Turno senza fascia: come il 1° turno
    if not fasce and user.is_staff:
        return None
    return fasce


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

    return oggi(request)


@login_required
def oggi(request):
    """Schermata "Oggi": il turno, con chi lavoro, i tasti per aggiungere i dati e i fermi impianto."""
    from .models import FermoImpianto

    dip = dipendente_di(request)
    if dip is None:
        return redirect('turni:home')
    contesto = contesto_oggi(request, dip)
    return render(request, 'turni/oggi.html', {
        **contesto,
        'dip': dip,
        'colleghi_oggi': _colleghi_oggi(contesto['turno_oggi'], dip),
        'fermi_aperti': FermoImpianto.objects.filter(ripartito_il__isnull=True).order_by('fermo_dal'),
        'oggi_data': timezone.localdate(),
    })


def _colleghi_oggi(turno, dip):
    """Fila di "storie" in Oggi: io e chi lavora nella mia stessa fascia, i Capi Turno per primi."""
    if not turno or not turno.lavora:
        return []

    def storia(t, io=False):
        parole = t.dipendente.nome_breve.split()
        return {
            'nome': 'Tu' if io else parole[-1],
            'iniziali': (parole[0][:1] + parole[-1][:1]).upper(),
            'foto': reverse('turni:foto_profilo_img', args=[t.dipendente_id]) + f'?v={t.dipendente.foto.name[-12:]}'
            if t.dipendente.foto else '',
            'capo': t.capoturno,
            'io': io,
        }

    altri = (
        Turno.objects.filter(data=turno.data, fascia=turno.fascia, settimana__pubblicata=True)
        .exclude(dipendente=dip)
        .select_related('dipendente')
    )
    altri = sorted((t for t in altri if t.lavora), key=lambda t: (not t.capoturno, t.dipendente.nome))
    return [storia(turno, io=True)] + [storia(t) for t in altri]


def contesto_oggi(request, dip):
    """Parte alta dell'Area personale: turno di oggi e domani, presa visione, avvisi del giorno."""
    turno = turno_attuale(dip)
    pulizie_da_fare = None
    promemoria = []
    if turno and turno.lavora:
        genera_pulizie(turno)
        pulizie_da_fare = turno.pulizie.exclude(stato__in=[Pulizia.Stato.FATTA, Pulizia.Stato.VERIFICATA]).count()
        promemoria = promemoria_di(turno)
    domani = timezone.localdate() + timedelta(days=1)
    da_verificare = pulizie_da_verificare(request.user)
    return {
        'turno_oggi': turno,
        'turno_etichetta': 'Stanotte' if turno and turno.data != timezone.localdate() else 'Oggi',
        'da_vedere': dip.modifiche_turno.filter(vista_il__isnull=True),
        'domani': dip.turni.filter(data=domani, settimana__pubblicata=True).first(),
        'pulizie_da_fare': pulizie_da_fare,
        'promemoria': promemoria,
        'capi_da_completare': capi_da_completare(request.user).filter(dipendente=dip)[:7],
        'mezzi_non_disponibili': __import__('turni.manutenzione', fromlist=['avvisi_per']).avvisi_per(request.user),
        'fasce_capo': FASCE_CAPO,
        'da_verificare': da_verificare,
        # il tasto "Pulizia" conta le mie da fare e, per il Capo Turno, quelle da verificare
        'badge_pulizia': (pulizie_da_fare or 0) + da_verificare,
        'piazzale': _per_resp_piazzale(request.user),
    }


def pulizie_da_verificare(utente):
    """Pulizie segnate "fatte" oggi che aspettano l'ok del Capo Turno (0 per chi non è Capo Turno oggi)."""
    oggi = timezone.localdate()
    if not e_capoturno(utente, oggi):
        return 0
    giorno, fasce = oggi, fasce_del_capo(utente, oggi)
    if fasce == set():  # Capo Turno della notte, la mattina dopo
        giorno, fasce = oggi - timedelta(days=1), fasce_del_capo(utente, oggi - timedelta(days=1))
    q = Pulizia.objects.filter(turno__data=giorno, stato=Pulizia.Stato.FATTA, ok_capoturno_il__isnull=True).exclude(
        elemento__convalida=ElementoPulizia.Convalida.PIAZZALE)
    if fasce is not None:
        q = q.filter(turno__fascia__in=fasce)
    return q.count()


def _per_resp_piazzale(utente):
    """Quante cose aspettano il responsabile piazzale (per il tasto in Oggi); None per gli altri."""
    generale = pulizia_generale_in_attesa()
    if not getattr(getattr(utente, 'dipendente', None), 'resp_piazzale', False):
        return None
    senza = sum(1 for c in capi_della_notte() if not c.pulizie.filter(richiesta_da__dipendente__resp_piazzale=True).exists())
    return {'da_fare': (1 if generale else 0) + da_convalidare_piazzale().count() + senza, 'notte_senza': senza}


FASCE_CAPO = [(Fascia.MATTINA, '1° turno'), (Fascia.POMERIGGIO, '2° turno'), (Fascia.NOTTE, 'Notte')]


def capi_da_completare(utente):
    """Turni da Capo Turno senza fascia che questa persona può completare (i suoi, o tutti per l'ufficio)."""
    from .richieste import e_responsabile

    qs = Turno.objects.filter(capoturno=True, fascia=Fascia.ALTRO, data__gte=timezone.localdate() - timedelta(days=1),
                              settimana__pubblicata=True).select_related('dipendente').order_by('data', 'dipendente__nome')
    if utente.is_staff or e_responsabile(utente):
        return qs
    dip = getattr(utente, 'dipendente', None)
    return qs.filter(dipendente=dip) if dip else qs.none()


@login_required
@require_POST
def fascia_capo(request):
    turno = get_object_or_404(capi_da_completare(request.user), pk=request.POST.get('turno'))
    fascia = request.POST.get('fascia')
    if fascia in dict(FASCE_CAPO):
        turno.fascia = fascia
        turno.save(update_fields=['fascia'])
        messages.success(request, f'{turno.dipendente.nome_breve} {turno.data:%d/%m}: Capo Turno {dict(FASCE_CAPO)[fascia]}.')
    dopo = request.POST.get('dopo') or ''
    if not url_has_allowed_host_and_scheme(dopo, allowed_hosts={request.get_host()}):
        dopo = reverse('turni:home')
    return redirect(dopo)


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
    fine = inizio + timedelta(days=6)  # una settimana per volta: più semplice
    if giorno and inizio <= giorno <= fine:
        scelto = giorno
    else:
        scelto = oggi if inizio <= oggi <= fine else inizio

    turni = {t.data: t for t in dip.turni.filter(data__range=(inizio, fine), settimana__pubblicata=True)}
    lunedi_oggi = oggi - timedelta(days=oggi.weekday())
    settimane = []
    for lun in (inizio,):
        distanza = (lun - lunedi_oggi).days // 7
        quale = {0: 'questa', 1: 'prossima', -1: 'scorsa'}.get(distanza, '')
        nome = f'Settimana {lun.isocalendar()[1]}' + (f' · {quale}' if quale else '')
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
            'saldo': saldi.residuo(dip),
            **contesto_oggi(request, dip),
            **__import__('turni.views_richieste', fromlist=['contesto_richieste']).contesto_richieste(dip),
        },
    )


ORDINE_GRUPPI = [Postazione.IMP1, Postazione.IMP2, Postazione.METALLI, Postazione.SABBIA, Postazione.ANALISI,
                 Postazione.PIAZZALE, Postazione.PALISTA, Postazione.AUTISTA, Postazione.MANUT,
                 Postazione.SUPERBI, Postazione.MULINO, Postazione.BARROTTI, Postazione.UFFICIO]


def nome_corto(dip):
    """'DI GIROLAMO GIANVITO' -> 'Di Girolamo G.': sta nella colonna stretta del telefono."""
    parole = dip.nome_breve.split()
    return ' '.join(parole[:-1] + [parole[-1][0] + '.']) if len(parole) > 1 else dip.nome_breve


@login_required
def settimana_tutti(request):
    """Come il file Excel: tutti i dipendenti della settimana, raggruppati per impianto/postazione,
    una casella colorata per giorno. Toccando il giorno di un collega si chiede il cambio."""
    from collections import Counter

    oggi = timezone.localdate()
    base = leggi_data(request.GET.get('settimana'), oggi)
    lunedi = base - timedelta(days=base.weekday())
    giorni = [lunedi + timedelta(days=i) for i in range(7)]
    mio = dipendente_di(request)

    per_dip = {}
    for t in Turno.objects.filter(data__in=giorni, settimana__pubblicata=True, dipendente__attivo=True).select_related('dipendente'):
        per_dip.setdefault(t.dipendente, {})[t.data] = t
    miei = per_dip.get(mio, {}) if mio else {}

    gruppi = {}
    for dip, turni in per_dip.items():
        lavoro = [t for t in turni.values() if t.lavora]
        posti = Counter(t.postazione for t in lavoro if t.postazione)
        if posti:
            chiave = posti.most_common(1)[0][0]
            titolo = Postazione(chiave).label
        else:
            fasce = Counter(t.fascia for t in lavoro)
            chiave = fasce.most_common(1)[0][0] if fasce else 'zz'
            titolo = {Fascia.GIORNALIERO: 'Giornalieri', Fascia.NOTTE: 'Notturno'}.get(chiave, 'Altri')
        celle = []
        for g in giorni:
            t = turni.get(g)
            mio_t = miei.get(g)
            cambiabile = (
                mio and dip != mio and t and mio_t and g > oggi
                and (t.fascia, t.postazione, t.capoturno) != (mio_t.fascia, mio_t.postazione, mio_t.capoturno)
            )
            celle.append({'turno': t, 'cambiabile': cambiabile, 'giorno': g})
        # dentro il gruppo: prima chi fa più mattine, poi pomeriggi, notti...
        fascia_tipica = Counter(t.fascia for t in lavoro).most_common(1)[0][0] if lavoro else 'zz'
        gruppi.setdefault((chiave, titolo), []).append(
            {'dip': dip, 'nome': nome_corto(dip), 'celle': celle, 'io': dip == mio,
             'ordine': (ORDINE_FASCE.index(fascia_tipica) if fascia_tipica in ORDINE_FASCE else 9, dip.nome)}
        )

    def ordine_gruppo(k):
        chiave = k[0]
        return ORDINE_GRUPPI.index(chiave) if chiave in ORDINE_GRUPPI else len(ORDINE_GRUPPI) + (chiave == 'zz')

    elenco = [(titolo, sorted(righe, key=lambda r: r['ordine'])) for (chiave, titolo), righe in sorted(gruppi.items(), key=lambda x: ordine_gruppo(x[0]))]
    mia_riga = next((r for _, righe in elenco for r in righe if r['io']), None)
    return render(
        request,
        'turni/settimana_tutti.html',
        {
            'gruppi': elenco,
            'giorni': giorni,
            'oggi': oggi,
            'lunedi': lunedi,
            'prec': lunedi - timedelta(days=7),
            'succ': lunedi + timedelta(days=7),
            'mio': mio,
            'mia_riga': mia_riga,
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
    # i Capi Turno stanno nel riquadro dell'impianto in cui lavorano (in azzurro); se nel file manca il turno
    # (es. "CAPO T. - Imp. 1") finiscono nel 1° turno finché non lo indicano
    posto = {p: i for i, p in enumerate(ORDINE_GRUPPI)}
    fascia_di = lambda t: Fascia.MATTINA if t.fascia == Fascia.ALTRO else t.fascia
    for fascia in ORDINE_FASCE[:-1]:
        della_fascia = sorted(
            (t for t in lavorano if fascia_di(t) == fascia),
            key=lambda t: (t.postazione == '', posto.get(t.postazione, 99), not t.capoturno, t.dipendente.nome),
        )
        if della_fascia:
            sottogruppi = [
                (k, list(v)) for k, v in groupby(della_fascia, key=lambda t: t.get_postazione_display() or 'Senza postazione')
            ]
            gruppi.append((Fascia(fascia).label, sottogruppi))
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

    # "Richiedi pulizia" funziona anche per chi oggi non è in turno (es. il Capo Turno a casa o l'ufficio)
    if request.GET.get('fai') == 'richiedi' and not request.GET.get('squadra'):
        resto = request.GET.copy()
        resto.pop('fai')
        return redirect(reverse('turni:richiedi_pulizia') + ('?' + resto.urlencode() if resto else ''))
    if request.GET.get('fai') == 'richiedi' or request.POST.get('azione') == 'richiedi':
        # "Assegna pulizie": il Capo Turno sceglie tra chi lavora nel suo turno
        alla_squadra = bool(request.GET.get('squadra') or request.POST.get('squadra')) and turno and turno.capoturno
        from .pulizie import puo_richiedere

        if not alla_squadra and not puo_richiedere(request.user):
            raise PermissionDenied
        colleghi = squadra_del_capo(turno) if alla_squadra else in_turno_oggi(escluso=dip)
        if request.method == 'POST':
            t = next((c for c in colleghi if str(c.pk) == request.POST.get('turno')), None)
            # dove e cosa: dalla scelta guidata, oppure solo scritti nel commento
            el = elemento_da_scelta(request.POST.get('cosa') or request.POST.get('elemento'))
            if alla_squadra and not request.POST.get('controllo'):
                # il Capo Turno assegna solo il controllo (es. vagli zig-zag) quando manca il manutentore
                return redirect(reverse('turni:pulizie') + '?fai=richiedi&squadra=1')
            if alla_squadra and request.POST.get('controllo'):
                # il controllo del promemoria (es. vagli zig-zag), solo se oggi tocca al turno del Capo Turno
                el = next((a['elemento'] for a in promemoria_di(turno) if str(a['elemento'].pk) == request.POST.get('controllo')
                           and not a['controllo']), None)
                if el is None:
                    messages.error(request, 'Controllo già assegnato.')
                    return redirect(reverse('turni:pulizie') + '?fai=richiedi&squadra=1')
            if not t:
                messages.error(request, 'Scegli a chi chiedere la pulizia.')
            else:
                try:
                    richiedi_pulizia(request.user, t, el, request.POST.get('nota', ''))
                except ValueError as e:
                    messages.error(request, str(e))
                else:
                    messages.success(request, f'Pulizia {"assegnata" if alla_squadra else "chiesta"} a {t.dipendente.nome_breve}.')
                    if request.POST.get('torna') == 'piazzale':
                        return redirect('turni:pulizie_piazzale')
                    return redirect('turni:home' if alla_squadra else 'turni:pulizie')
        return render(request, 'turni/pulizie_richiedi.html', {
            'colleghi': colleghi, 'luoghi': scelte_pulizia(), 'alla_squadra': alla_squadra,
            'scelto': request.GET.get('turno', ''), 'nota': request.GET.get('nota', '')[:300], 'torna': request.GET.get('torna', ''),
            'controlli': [a for a in promemoria_di(turno) if not a['controllo']] if alla_squadra else []})

    if turno is None or not turno.lavora:
        return render(request, 'turni/pulizia.html', {'turno': None})

    if request.method == 'POST':
        azione = request.POST.get('azione')
        if azione == 'pin_tutti':
            senza = list(Dipendente.objects.filter(attivo=True, utente__isnull=True).order_by('nome'))
            if not senza:
                messages.info(request, 'Tutti i dipendenti attivi hanno già un accesso.')
                return redirect('turni:dipendenti')
            return _consegna_credenziali(request, senza)
        if azione == 'libera':
            # "Aggiungi pulizia": foto prima e dopo, e dove/cosa scritti nel commento
            nota = (request.POST.get('nota') or '').strip()
            if not nota:
                messages.error(request, 'Scrivi dove e cosa hai pulito.')
                return redirect(reverse('turni:pulizie_turno', args=[turno.pk]) + '?fai=libera')
            p = Pulizia(turno=turno, elemento=None, aggiunta_da_operaio=True, nota=nota[:300])
            if not _foto_pulizia(request, p):
                return redirect(reverse('turni:pulizie_turno', args=[turno.pk]) + '?fai=libera')
            p.stato, p.fatta_il = Pulizia.Stato.FATTA, timezone.now()
            if turno.capoturno:
                # le pulizie del Capo Turno non aspettano nessuno: vanno subito in archivio
                p.stato, p.verificata_da, p.verificata_il = Pulizia.Stato.VERIFICATA, request.user, timezone.now()
            p.save()
            messages.success(request, 'Pulizia salvata in archivio.' if turno.capoturno else 'Pulizia inviata al Capo Turno.')
            return redirect('turni:pulizie')
        if azione == 'aggiungi':
            elemento = get_object_or_404(mezzi_aggiungibili(turno), pk=request.POST.get('elemento'))
            Pulizia.objects.get_or_create(turno=turno, elemento=elemento, defaults={'aggiunta_da_operaio': True})
        elif azione == 'aggiuntiva':
            # pulizia in più, fatta di propria iniziativa: entra già come fatta, con le foto
            elemento = elemento_da_scelta(request.POST.get('cosa') or request.POST.get('elemento'))
            if not elemento or turno.pulizie.filter(elemento=elemento).exists():
                messages.error(request, 'Scegli dove e cosa hai pulito (non una pulizia già nella tua lista).')
                return redirect(reverse('turni:pulizie_turno', args=[turno.pk]) + '?fai=aggiuntiva')
            p = Pulizia(turno=turno, elemento=elemento, aggiunta_da_operaio=True)
            if not _foto_pulizia(request, p):
                return redirect(reverse('turni:pulizie_turno', args=[turno.pk]) + '?fai=aggiuntiva')
            p.nota = request.POST.get('nota', '')[:300]
            p.stato, p.fatta_il = Pulizia.Stato.FATTA, timezone.now()
            p.save()
            messages.success(request, f'Pulizia aggiuntiva completata: {elemento.nome}.')
        else:
            p = get_object_or_404(turno.pulizie, pk=request.POST.get('pulizia'))
            if p.stato == Pulizia.Stato.VERIFICATA:
                messages.info(request, 'Questa pulizia è già stata verificata.')
            elif azione == 'rimuovi' and p.aggiunta_da_operaio and p.stato == Pulizia.Stato.DA_FARE:
                p.delete()
            elif azione == 'impedita':
                # foto obbligatoria: giustifica perché la pulizia non si è potuta fare
                if not request.FILES.get('foto'):
                    messages.error(request, 'Serve una foto che mostri il motivo.')
                    return redirect(reverse('turni:pulizie_turno', args=[turno.pk]) + f'?fai=impedimento&voce={p.pk}')
                if not _foto_pulizia(request, p):
                    return redirect(reverse('turni:pulizie_turno', args=[turno.pk]) + f'?fai=impedimento&voce={p.pk}')
                motivo = request.POST.get('motivo') if request.POST.get('motivo') in Pulizia.MOTIVI_IMPEDIMENTO else 'Altro'
                nota = request.POST.get('nota', '').strip()
                p.nota = (motivo + (f': {nota}' if nota else ''))[:300]
                p.stato, p.fatta_il = Pulizia.Stato.IMPEDITA, timezone.now()
                p.save()
                from . import manutenzione as mn

                mn.avvisa(mn.capiturno_oggi(), request.user, f'🧹 Pulizia non eseguibile · {dip.nome_breve}',
                          f'{p.titolo}: {p.nota}', reverse('turni:capoturno'))
                messages.success(request, f'Impedimento segnalato: {p.titolo}.')
            elif azione == 'fatta':
                torna = reverse('turni:pulizie_turno', args=[turno.pk]) + f'?fai=assegnata&voce={p.pk}' + ('&da=oggi' if request.POST.get('da') == 'oggi' else '')
                el = p.elemento
                manca = ''
                if not p.disponibile:
                    manca = f'{p.titolo} si fa dalle {timezone.localtime(p.da_quando):%H:%M}.'
                elif el and el.modo == ElementoPulizia.Modo.PULIZIA_FOTO and not (
                        (request.FILES.get('foto_prima') or p.foto_prima) and (request.FILES.get('foto') or p.foto)):
                    manca = 'Servono la foto prima e la foto dopo.'
                elif el and el.modo == ElementoPulizia.Modo.CONTROLLO_FOTO and not request.FILES.get('foto'):
                    manca = 'Serve la foto del controllo.'
                elif el and el.modo == ElementoPulizia.Modo.FOTO_DOPO and not (request.FILES.get('foto') or p.foto):
                    manca = 'Serve la foto dopo la pulizia.'
                if manca:
                    messages.error(request, manca)
                    return redirect(torna)
                if not _foto_pulizia(request, p):
                    return redirect(torna)
                p.nota = request.POST.get('nota', '')[:300] or p.nota
                p.stato = Pulizia.Stato.FATTA
                p.fatta_il = timezone.now()
                p.ok_capoturno_da, p.ok_capoturno_il = None, None  # rifatta: si ricomincia dal Capo Turno
                if el and el.convalida == ElementoPulizia.Convalida.NESSUNA:
                    # i controlli di fine turno non aspettano nessuno: vanno subito in archivio
                    p.stato, p.verificata_il = Pulizia.Stato.VERIFICATA, timezone.now()
                p.save()
                if el and el.convalida == ElementoPulizia.Convalida.PIAZZALE:
                    from . import manutenzione as mn

                    mn.avvisa(resp_piazzale(), request.user, f'✅ {el.tasto or p.titolo} · {dip.nome_breve}', 'Da convalidare',
                              reverse('turni:pulizie_piazzale'))
                    messages.success(request, f'{p.titolo}: inviato al responsabile piazzale.')
                else:
                    messages.success(request, f'{"Controllo fatto" if el and el.controllo else "Pulizia completata"}: {p.titolo}.')
            elif azione == 'problema' and p.elemento_id and p.elemento.controllo:
                # controllo con un problema (es. la pala): nota obbligatoria; avvisa Capo Turno e manutenzione.
                # Se il controllo è legato a una macchina (es. i vagli zig-zag) diventa una segnalazione di guasto, con la foto.
                from . import manutenzione as mn

                torna = reverse('turni:pulizie_turno', args=[turno.pk]) + f'?fai=assegnata&voce={p.pk}' + ('&da=oggi' if request.POST.get('da') == 'oggi' else '')
                nota = request.POST.get('nota', '').strip()
                macchina = p.elemento.macchina
                if not nota or (macchina and not request.FILES.get('foto')):
                    messages.error(request, 'Scrivi qual è il problema' + (' e fai la foto.' if macchina else '.'))
                    return redirect(torna)
                if macchina:
                    try:
                        mn.segnala(request.user, macchina, f'{p.titolo}: {nota}', False, request.FILES['foto'])
                    except Exception:
                        messages.error(request, 'La foto non si legge: riprova a scattarla.')
                        return redirect(torna)
                    request.FILES['foto'].seek(0)
                if not _foto_pulizia(request, p):
                    return redirect(torna)
                p.nota, p.stato, p.fatta_il = f'Problema: {nota}'[:300], Pulizia.Stato.IMPEDITA, timezone.now()
                p.save()
                if not macchina:
                    mn.avvisa(mn.capiturno_oggi() + mn.responsabili(), request.user, f'⚠️ {p.titolo} · {dip.nome_breve}', nota,
                              reverse('turni:capoturno'))
                messages.success(request, f'Problema segnalato: {p.titolo}' + (' (inviato alla manutenzione).' if macchina else '.'))
            elif azione == 'passa' and turno.capoturno and p.stato == Pulizia.Stato.DA_FARE:
                t = next((c for c in squadra_del_capo(turno) if str(c.pk) == request.POST.get('a')), None)
                if not t:
                    messages.error(request, 'Scegli a chi passarla.')
                    return redirect(reverse('turni:pulizie_turno', args=[turno.pk]) + f'?fai=assegnata&voce={p.pk}')
                try:
                    passa_pulizia(request.user, p, t)
                except ValueError as e:
                    messages.error(request, str(e))
                else:
                    messages.success(request, f'{p.titolo}: passata a {t.dipendente.nome_breve}.')
                return redirect('turni:pulizie')
        # aperta dal promemoria in Oggi (es. controllo vagli zig-zag): si torna a Oggi
        if request.POST.get('da') == 'oggi':
            return redirect('turni:home')
        return redirect('turni:pulizie_turno', turno.pk)

    if request.GET.get('fai') == 'libera':
        return render(request, 'turni/pulizia_aggiungi.html', {'turno': turno})
    if not request.GET.get('fai'):
        # pagina "Pulizia": i due tasti, e sopra le pulizie ancora da fare (chieste dai colleghi, da rifare
        # o assegnate dalle regole di "Mezzi e zone", se ce ne sono)
        genera_pulizie(turno)
        richieste = turno.pulizie.filter(stato__in=[Pulizia.Stato.DA_FARE, Pulizia.Stato.SEGNALATA])
        from .pulizie import puo_richiedere

        return render(request, 'turni/pulizia.html', {
            'turno': turno, 'richieste': richieste.select_related('elemento', 'richiesta_da__dipendente'),
            'resp_piazzale': e_resp_piazzale(request.user), 'puo_richiedere': puo_richiedere(request.user),
            'e_capo': e_capoturno(request.user, timezone.localdate()), 'da_verificare': pulizie_da_verificare(request.user)})

    genera_pulizie(turno)
    voci = list(turno.pulizie.select_related('elemento', 'richiesta_da__dipendente'))
    da_fare = [v for v in voci if v.stato in (Pulizia.Stato.DA_FARE, Pulizia.Stato.SEGNALATA)]
    contesto = {
        'turno': turno,
        'voci': voci,
        'da_fare': da_fare,
        'fatte': sum(v.stato in (Pulizia.Stato.FATTA, Pulizia.Stato.VERIFICATA) for v in voci),
        'completate': [v for v in voci if v.stato in (Pulizia.Stato.FATTA, Pulizia.Stato.VERIFICATA, Pulizia.Stato.IMPEDITA)],
        'motivi': Pulizia.MOTIVI_IMPEDIMENTO,
        'recenti': recenti,
        'fai': request.GET.get('fai'),
        'da': request.GET.get('da', ''),
    }
    if contesto['fai'] in ('assegnata', 'impedimento'):
        scelta = next((v for v in da_fare if str(v.pk) == request.GET.get('voce')), None)
        if scelta is None and len(da_fare) == 1:
            scelta = da_fare[0]  # una sola pulizia assegnata: si va dritti al modulo
        contesto['voce'] = scelta
        # il Capo Turno può passare a un operatore le pulizie che gli arrivano (es. dal responsabile piazzale, la notte)
        if scelta and turno.capoturno and scelta.richiesta_da_id and scelta.stato == Pulizia.Stato.DA_FARE:
            contesto['squadra'] = squadra_del_capo(turno)
    elif contesto['fai'] == 'aggiuntiva':
        contesto['luoghi'] = scelte_pulizia(escludi=turno.pulizie.values_list('elemento_id', flat=True))
    return render(request, 'turni/pulizie.html', contesto)


def _foto_pulizia(request, p):
    """Salva la foto prima e quella dopo, se ci sono. False (con il messaggio) se una non si legge."""
    for campo in ('foto_prima', 'foto'):
        if request.FILES.get(campo):
            try:
                salva_foto(p, request.FILES[campo], campo)
            except Exception:
                messages.error(request, 'La foto non si legge: riprova a scattarla.')
                return False
    return True


@login_required
def capoturno(request):
    oggi = timezone.localdate()
    giorno = leggi_data(request.GET.get('giorno'), oggi)
    if not e_capoturno(request.user, giorno):
        raise PermissionDenied
    mie_fasce = fasce_del_capo(request.user, giorno)
    if mie_fasce == set() and 'giorno' not in request.GET:
        # Capo Turno della notte, la mattina dopo: la sua verifica è sul giorno in cui è iniziato il turno
        ieri = giorno - timedelta(days=1)
        if fasce_del_capo(request.user, ieri):
            return redirect(f'{request.path}?giorno={ieri.isoformat()}')

    if request.method == 'POST':
        p = get_object_or_404(Pulizia, pk=request.POST.get('pulizia'), turno__data=giorno)
        if mie_fasce is not None and p.turno.fascia not in mie_fasce:
            messages.error(request, 'Puoi verificare solo le pulizie del turno in cui sei Capo Turno.')
        elif p.turno.dipendente.utente_id == request.user.pk and not request.user.is_staff:
            messages.error(request, 'Le tue pulizie le verifica un altro Capo Turno.')
        elif p.elemento_id and p.elemento.convalida == ElementoPulizia.Convalida.PIAZZALE and not e_resp_piazzale(request.user):
            messages.error(request, 'Questa la convalida il responsabile piazzale.')
        elif (request.POST.get('azione') == 'verifica' and p.elemento_id
              and p.elemento.convalida == ElementoPulizia.Convalida.CT_RP):
            # primo passaggio: l'ok del Capo Turno, poi la convalida il responsabile piazzale
            p.ok_capoturno_da, p.ok_capoturno_il = request.user, timezone.now()
            p.nota_verifica = request.POST.get('nota', '')[:300]
            p.save()
            from . import manutenzione as mn

            mn.avvisa(resp_piazzale(), request.user, f'✅ {p.titolo} · {p.turno.dipendente.nome_breve}',
                      'Ok del Capo Turno: da convalidare', reverse('turni:pulizie_piazzale'))
            messages.success(request, f'{p.titolo}: ok, inviata al responsabile piazzale.')
        else:
            ok = request.POST.get('azione') == 'verifica'
            p.ok_capoturno_da, p.ok_capoturno_il = None, None
            p.stato = Pulizia.Stato.VERIFICATA if ok else Pulizia.Stato.SEGNALATA
            p.verificata_da = request.user
            p.verificata_il = timezone.now()
            p.nota_verifica = request.POST.get('nota', '')[:300]
            p.save()
        return redirect(f"{request.path}?giorno={giorno.isoformat()}#d{p.turno_id}")

    del_giorno = Turno.objects.filter(data=giorno, fascia__in=FASCE_LAVORATIVE if mie_fasce is None else mie_fasce)
    for t in del_giorno:
        genera_pulizie(t)
    turni = list(
        del_giorno.select_related('dipendente')
        .prefetch_related('pulizie__elemento')
        .annotate(
            n_voci=Count('pulizie'),
            n_fatte=Count('pulizie', filter=Q(pulizie__stato__in=[Pulizia.Stato.FATTA, Pulizia.Stato.VERIFICATA])),
            n_da_verificare=Count('pulizie', filter=Q(pulizie__stato=Pulizia.Stato.FATTA, pulizie__ok_capoturno_il__isnull=True) & ~Q(
                pulizie__elemento__convalida=ElementoPulizia.Convalida.PIAZZALE)),
        )
    )
    fascia = request.GET.get('fascia', '')
    if fascia:
        turni = [t for t in turni if t.fascia == fascia]
    if mie_fasce is not None:
        turni = [t for t in turni if t.n_voci]  # al Capo Turno solo chi ha pulizie da seguire
    turni.sort(key=lambda t: (-t.n_da_verificare, ORDINE_FASCE.index(t.fascia), t.dipendente.nome))
    from .models import AvvisoAssenza

    promemoria = {}
    promemoria_q = Pulizia.objects.filter(turno__data=giorno, elemento__promemoria=True)
    if mie_fasce is not None:
        promemoria_q = promemoria_q.filter(turno__fascia__in=mie_fasce)
    for p in promemoria_q.select_related('elemento', 'turno__dipendente'):
        promemoria.setdefault((p.elemento.nome, timezone.localtime(p.da_quando), p.turno.get_fascia_display()), []).append(p)
    return render(
        request,
        'turni/capoturno.html',
        {
            'promemoria': [(n, quando, fascia, voci) for (n, quando, fascia), voci in sorted(promemoria.items(), key=lambda x: x[0][1])],
            'avvisi': AvvisoAssenza.objects.filter(data=giorno, annullato_il__isnull=True).select_related('dipendente'),
            'giorno': giorno,
            'turni': turni,
            'fascia': fascia,
            # sigle come nel calendario, così la barra sta su una riga; il Capo Turno vede solo il suo turno (niente barra)
            'fasce': [
                (f, Turno.SIGLE[f], Turno(fascia=f).classe_fascia)
                for f in (Fascia.MATTINA, Fascia.POMERIGGIO, Fascia.NOTTE, Fascia.GIORNALIERO)
            ] if mie_fasce is None else [],
            'mio_turno': ' e '.join(Fascia(f).label for f in ORDINE_FASCE if f in (mie_fasce or ())),
            'non_capo': mie_fasce == set(),
            'prec': giorno - timedelta(days=1),
            'succ': giorno + timedelta(days=1),
        },
    )


@login_required
def richiedi_pulizia_vista(request):
    """«Richiedi pulizia» (responsabile impianto e responsabile piazzale): area → giorno e turno → persona, con la foto."""
    from .models import Luogo
    from .pulizie import LUOGHI_PULIZIA, POSTAZIONI_AREA, in_turno, puo_richiedere
    from .views_manutenzione import ICONE_LUOGHI

    if not puo_richiedere(request.user):
        raise PermissionDenied
    dati = request.POST if request.method == 'POST' else request.GET
    area = dati.get('area') if dati.get('area') in LUOGHI_PULIZIA else ''
    giorno = leggi_data(dati.get('giorno'), None)
    # come in «Turni di tutti»: sigla colorata, ore sotto
    fasce = [(Fascia.MATTINA, '1T', '06–14', 'f-mattina'), (Fascia.POMERIGGIO, '2T', '14–22', 'f-pomeriggio'),
             (Fascia.NOTTE, 'N', '22–06', 'f-notte'), (Fascia.GIORNALIERO, 'G', '08–17', 'f-giorno')]
    fascia = dati.get('fascia') if dati.get('fascia') in [f[0] for f in fasce] else ''
    oggi = timezone.localdate()
    if giorno and giorno < oggi:
        giorno = None
    torna = dati.get('torna', '')
    contesto = {'area': area, 'giorno': giorno, 'fascia': fascia, 'torna': torna, 'oggi': oggi,
                'nota': dati.get('nota', '')[:300], 'scelto': dati.get('turno', ''), 'fasce': fasce}
    if area:
        contesto['nome_area'] = Luogo(area).label
    if area and giorno and fascia:
        io = getattr(dipendente_di(request), 'pk', None)
        # solo chi lavora nell'area scelta
        vicini = [t for t in in_turno(giorno, fascia, area)[0] if t.dipendente_id != io]
        if request.method == 'POST':
            t = next((x for x in vicini if str(x.pk) == request.POST.get('turno')), None)
            testo = request.POST.get('nota', '').strip()
            foto = request.FILES.get('foto')
            errore = 'Scegli a chi assegnarla.' if not t else 'Fai la foto di cosa va pulito.' if not foto else ''
            if not errore:
                p = Pulizia(turno=t, richiesta_da=request.user, nota=(Luogo(area).label + (f': {testo}' if testo else ''))[:300])
                try:
                    salva_foto(p, foto, 'foto_richiesta')
                except Exception:
                    errore = 'La foto non si legge: riprova a scattarla.'
            if errore:
                messages.error(request, errore)
            else:
                p.save()
                from . import push

                if t.dipendente.utente_id:
                    da = getattr(getattr(request.user, 'dipendente', None), 'nome_breve', None) or request.user.get_username()
                    push.invia([t.dipendente.utente_id], '🧹 Ti chiedono una pulizia', f'{p.titolo} (da {da})',
                               f'/turni/pulizie/{t.pk}/')
                messages.success(request, f'Pulizia assegnata a {t.dipendente.nome_breve} · {giorno:%d/%m} {Fascia(fascia).label}.')
                return redirect('turni:pulizie_piazzale' if torna == 'piazzale' else 'turni:pulizie')
        contesto['vicini'] = vicini
    else:
        contesto['aree'] = [(v, Luogo(v).label, ICONE_LUOGHI.get(v, '📍')) for v in LUOGHI_PULIZIA]
        # la settimana tutta in una riga, da lunedì; si va avanti di settimana in settimana
        lunedi = leggi_data(dati.get('settimana'), None) or giorno or oggi
        lunedi -= timedelta(days=lunedi.weekday())
        questo = oggi - timedelta(days=oggi.weekday())
        lunedi = max(lunedi, questo)
        contesto.update({'giorni': [lunedi + timedelta(days=i) for i in range(7)], 'lunedi': lunedi,
                         'prec': lunedi - timedelta(days=7) if lunedi > questo else None, 'succ': lunedi + timedelta(days=7)})
    return render(request, 'turni/richiedi_pulizia.html', contesto)


@login_required
def pulizie_piazzale(request):
    """Responsabile piazzale: pulizie della notte ai Capi Turno (entro le 17), convalida del piazzale,
    pulizia generale dell'Impianto 2 ogni 2 settimane."""
    from .models import PuliziaGenerale

    if not e_resp_piazzale(request.user):
        raise PermissionDenied
    generale = pulizia_generale_in_attesa()
    if request.method == 'POST':
        azione = request.POST.get('azione')
        if azione in ('generale_si', 'generale_no') and generale:
            generale.esito = PuliziaGenerale.Esito.DA_FARE if azione == 'generale_si' else PuliziaGenerale.Esito.NON_NECESSARIA
            generale.deciso_da, generale.deciso_il = request.user, timezone.now()
            generale.save()
            if azione == 'generale_si':
                return redirect(reverse('turni:richiedi_pulizia') + '?' + urlencode(
                    {'area': 'IMP2', 'torna': 'piazzale', 'nota': 'Pulizia generale Impianto 2'}))
            messages.success(request, 'Pulizia generale non necessaria: te la richiedo tra 2 settimane.')
        elif azione in ('convalida', 'rifare'):
            p = get_object_or_404(da_convalidare_piazzale(), pk=request.POST.get('pulizia'))
            p.stato = Pulizia.Stato.VERIFICATA if azione == 'convalida' else Pulizia.Stato.SEGNALATA
            p.verificata_da, p.verificata_il = request.user, timezone.now()
            p.nota_verifica = request.POST.get('nota', '')[:300]
            p.save()
            messages.success(request, f'{p.titolo}: {"convalidato" if azione == "convalida" else "da rifare"}.')
        return redirect('turni:pulizie_piazzale')

    capi = capi_della_notte()
    for c in capi:
        c.ricevute = list(c.pulizie.filter(richiesta_da__dipendente__resp_piazzale=True))
    adesso = timezone.localtime()
    return render(request, 'turni/pulizie_piazzale.html', {
        'generale': generale,
        'ultima_generale': PuliziaGenerale.objects.exclude(esito='').first(),
        'capi': capi,
        'ora_notte': ORA_NOTTE,
        'in_ritardo': adesso.hour >= ORA_NOTTE and any(not c.ricevute for c in capi),
        'da_convalidare': da_convalidare_piazzale(),
    })


@login_required
def archivio(request):
    """Un solo posto per gli archivi: pulizie, manutenzione, produzione, analisi, fermi impianto."""
    return render(request, 'turni/archivio.html')


@login_required
def archivio_pulizie(request):
    """Pulizie approvate dal Capo Turno: giorno -> turno -> impianto -> foto e commenti."""
    oggi = timezone.localdate()
    approvate = Pulizia.objects.filter(stato=Pulizia.Stato.VERIFICATA).select_related('turno__dipendente', 'elemento')
    giorno = leggi_data(request.GET.get('giorno'), None)
    fascia = request.GET.get('fascia', '')
    posto = request.GET.get('posto', '')
    contesto = {'giorno': giorno, 'fascia': fascia, 'posto': posto}
    if not giorno:
        dal = oggi - timedelta(days=30)
        conta = approvate.filter(turno__data__gte=dal).values('turno__data').annotate(n=Count('id')).order_by('-turno__data')
        contesto['giorni'] = [(r['turno__data'], r['n']) for r in conta]
    else:
        del_giorno = approvate.filter(turno__data=giorno)
        fascia_di = lambda t: Fascia.MATTINA if t.fascia == Fascia.ALTRO else t.fascia
        if not fascia:
            capi = {fascia_di(t): t.dipendente.nome_breve for t in Turno.objects.filter(data=giorno, capoturno=True).select_related('dipendente')}
            conta = {}
            for p in del_giorno:
                conta[fascia_di(p.turno)] = conta.get(fascia_di(p.turno), 0) + 1
            contesto['fasce'] = [(f, Turno.SIGLE[f], Turno(fascia=f).classe_fascia, Fascia(f).label, conta[f], capi.get(f))
                                 for f in ORDINE_FASCE if f in conta]
        else:
            della_fascia = [p for p in del_giorno if fascia_di(p.turno) == fascia]
            contesto['nome_fascia'] = Fascia(fascia).label if fascia in Fascia.values else fascia
            if not posto:
                conta = {}
                for p in della_fascia:
                    conta[p.turno.postazione] = conta.get(p.turno.postazione, 0) + 1
                ordine = {x: i for i, x in enumerate(ORDINE_GRUPPI)}
                contesto['posti'] = sorted(((k, Postazione(k).label if k else 'Senza postazione', n) for k, n in conta.items()),
                                           key=lambda x: ordine.get(x[0], 99))
            else:
                contesto['nome_posto'] = Postazione(posto).label if posto in Postazione.values else 'Senza postazione'
                contesto['pulizie'] = sorted((p for p in della_fascia if p.turno.postazione == posto), key=lambda p: p.fatta_il or p.verificata_il)
    return render(request, 'turni/archivio_pulizie.html', contesto)


@login_required
def foto(request, pulizia_id):
    p = get_object_or_404(Pulizia.objects.select_related('turno__dipendente'), pk=pulizia_id)
    proprietario = p.turno.dipendente.utente_id == request.user.pk
    # le pulizie approvate stanno nell'archivio: le foto le vedono tutti i dipendenti
    in_archivio = p.stato == Pulizia.Stato.VERIFICATA and (dipendente_di(request) or request.user.is_staff)
    if not (proprietario or in_archivio or e_capoturno(request.user, p.turno.data) or p.richiesta_da_id == request.user.pk):
        raise PermissionDenied
    f = {'prima': p.foto_prima, 'richiesta': p.foto_richiesta}.get(request.GET.get('quale'), p.foto)
    if not f:
        raise Http404
    return FileResponse(f.open('rb'), content_type='image/jpeg')


# ---------------------------------------------------------------- foto profilo


@login_required
@require_POST
def foto_profilo(request):
    """Il dipendente carica la foto del suo cerchietto: ritagliata quadrata, 400 px, JPEG."""
    from io import BytesIO

    from django.core.files.base import ContentFile
    from PIL import Image, ImageOps

    from .pulizie import MAX_FOTO

    dip = dipendente_di(request)
    if dip is None:
        raise PermissionDenied
    file = request.FILES.get('foto')
    try:
        if not file or file.size > MAX_FOTO:
            raise ValueError
        img = ImageOps.fit(ImageOps.exif_transpose(Image.open(file)).convert('RGB'), (400, 400))
        buf = BytesIO()
        img.save(buf, 'JPEG', quality=82, optimize=True)
    except Exception:
        messages.error(request, 'Foto non valida o troppo grande.')
        return redirect('turni:miei_turni')
    vecchia = dip.foto.name
    dip.foto.save(f'profilo-{dip.pk}.jpg', ContentFile(buf.getvalue()), save=True)
    if vecchia and vecchia != dip.foto.name:
        dip.foto.storage.delete(vecchia)
    messages.success(request, 'Foto profilo aggiornata.')
    return redirect('turni:miei_turni')


@login_required
def foto_profilo_img(request, dip_id):
    """Le foto profilo le vedono i colleghi e l'ufficio, non chi è fuori dall'app."""
    if not (dipendente_di(request) or request.user.is_staff):
        raise PermissionDenied
    dip = get_object_or_404(Dipendente, pk=dip_id)
    if not dip.foto:
        raise Http404
    return FileResponse(dip.foto.open('rb'), content_type='image/jpeg')


# ---------------------------------------------------------------- ufficio


def avvisa_modifiche(settimana, modifiche):
    """Notifica a tutti che i turni sono cambiati; a chi è toccato, il dettaglio e la richiesta di presa visione."""
    from . import push

    per_persona = {}
    for m in modifiche:
        per_persona.setdefault(m.dipendente, []).append(m)
    interessati = set()
    for dip, righe in per_persona.items():
        if dip.utente_id:
            interessati.add(dip.utente_id)
            testo = '; '.join(f'{m.data:%d/%m} {m.dopo}' for m in righe[:3])
            push.invia([dip.utente_id], 'Il tuo turno è cambiato', f'{testo}. Apri e premi "Presa visione".', '/turni/')
    altri = Dipendente.objects.filter(attivo=True, utente__isnull=False).exclude(utente_id__in=interessati)
    push.invia(altri.values_list('utente_id', flat=True), 'Turni aggiornati', f'Nuova versione dei turni ({settimana}).', '/turni/settimana/')


@login_required
@require_POST
def presa_visione(request):
    from .models import ModificaTurno

    dip = dipendente_di(request)
    if dip:
        ModificaTurno.objects.filter(dipendente=dip, vista_il__isnull=True).update(vista_il=timezone.now())
        messages.success(request, 'Grazie, presa visione registrata.')
    return redirect('turni:messaggi')


@staff_member_required
def importa_turni(request):
    if request.method == 'POST':
        form = ImportaForm(request.POST, request.FILES)
        if form.is_valid():
            f = form.cleaned_data['file']
            lunedi = form.cleaned_data['lunedi'] or importa.lunedi_dal_file(f) or importa.lunedi_da_nome_file(f.name)
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
    from .models import ModificaTurno

    settimane = Settimana.objects.annotate(n=Count('turni__dipendente', distinct=True))[:8]
    modifiche = ModificaTurno.objects.filter(creata_il__gte=timezone.now() - timedelta(days=14)).select_related('dipendente').order_by('vista_il', '-creata_il')[:60]
    return render(request, 'turni/ufficio_importa.html', {'form': form, 'settimane': settimane, 'modifiche': modifiche})


@staff_member_required
def anteprima(request):
    dati = request.session.get('import_turni')
    if not dati:
        return redirect('turni:importa')
    letta = importa.da_sessione(dati)
    if request.method == 'POST':
        from .models import ModificaTurno

        ultima = ModificaTurno.objects.order_by('-pk').values_list('pk', flat=True).first() or 0
        settimana, nuovi, mantenuti = importa.salva_settimana(
            letta, request.user, request.session.get('import_nome_file', '')
        )
        modifiche = ModificaTurno.objects.filter(pk__gt=ultima).select_related('dipendente')
        if modifiche:
            avvisa_modifiche(settimana, modifiche)
            messages.info(request, f'Turni cambiati a {len({m.dipendente_id for m in modifiche})} persone: devono dare la presa visione.')
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


# Calendario inventato per far vedere l'app a chi non ha turni (es. un dipendente fittizio):
# due settimane con tutti i tipi di turno, così compaiono tutti i colori.
TURNI_PROVA = [
    ('1T- Imp. 1', '1T- Imp. 1', 'RIP', '2T-Imp. 2', '2T-Imp. 2', 'CAPO T. 1T - Imp. 1', 'RIP'),
    ('N/palista', 'N/palista', 'RIP', 'G-Analisi', 'FERIE', 'FERIE', 'RIP'),
]


def genera_turni_prova(dip, capo=False):
    """capo=True: Capo Turno del 1° turno all'Impianto 1 ogni giorno, per provare la verifica delle pulizie."""
    oggi = timezone.localdate()
    lunedi = oggi - timedelta(days=oggi.weekday())
    if capo:
        for n in range(2):
            inizio = lunedi + timedelta(days=7 * n)
            settimana, _ = Settimana.objects.get_or_create(lunedi=inizio, defaults={'file_originale': 'turni di prova'})
            for i in range(7):
                Turno.objects.update_or_create(
                    dipendente=dip, data=inizio + timedelta(days=i),
                    defaults={'settimana': settimana, 'codice': '1T · Impianto 1 · Capo Turno', 'fascia': Fascia.MATTINA,
                              'postazione': Postazione.IMP1, 'capoturno': True, 'ruolo': 'CT',
                              'posto': 'Impianto 1 · Capo Turno', 'incarichi': 'IMP1/CT', 'nota_modifica': 'Turno di prova'},
                )
        return
    for n, codici in enumerate(TURNI_PROVA):
        inizio = lunedi + timedelta(days=7 * n)
        settimana, _ = Settimana.objects.get_or_create(lunedi=inizio, defaults={'file_originale': 'turni di prova'})
        for i, codice in enumerate(codici):
            c = importa.interpreta_codice(codice)
            Turno.objects.update_or_create(
                dipendente=dip,
                data=inizio + timedelta(days=i),
                defaults={
                    'settimana': settimana,
                    'codice': c.codice,
                    'fascia': c.fascia,
                    'postazione': c.postazione,
                    'capoturno': c.capoturno,
                    'nota_modifica': 'Turno di prova',
                },
            )


@staff_member_required
def dipendenti(request):
    if request.method == 'POST':
        azione = request.POST.get('azione')
        if azione == 'pin_tutti':
            senza = list(Dipendente.objects.filter(attivo=True, utente__isnull=True).order_by('nome'))
            if not senza:
                messages.info(request, 'Tutti i dipendenti attivi hanno già un accesso.')
                return redirect('turni:dipendenti')
            return _consegna_credenziali(request, senza)
        if azione == 'aggiungi':
            nome = ' '.join((request.POST.get('nome') or '').split()).upper()
            if len(nome) < 3:
                messages.error(request, 'Scrivi cognome e nome.')
            elif Dipendente.objects.filter(nome=nome).exists():
                messages.error(request, f"{nome.title()} è già nell'elenco.")
            else:
                simile = importa.trova_dipendente(nome, list(Dipendente.objects.all()))
                dip = Dipendente.objects.create(nome=nome)
                messages.success(request, f'{dip.nome_breve} aggiunto. Ora puoi creare il suo accesso.')
                if simile:
                    messages.warning(request, f'Attenzione: assomiglia a {simile.nome_breve}. Se è la stessa persona, elimina il doppione.')
            return redirect('turni:dipendenti')

        dip = get_object_or_404(Dipendente, pk=request.POST.get('dipendente'))
        if azione == 'mansione':
            from .models import Mansione

            scelte = [m for m in request.POST.getlist('mansione') if m in Mansione.values]
            if scelte:
                dip.mansione = ','.join(scelte)
                dip.save(update_fields=['mansione'])
                messages.success(request, f'{dip.nome_breve}: {dip.mansioni_display.lower()}.')
            else:
                messages.error(request, 'Serve almeno una mansione.')
            return redirect('turni:dipendenti')
        if azione in ('turni_prova', 'turni_prova_capo'):
            if dip.turni.exists():
                messages.error(request, f'{dip.nome_breve} ha già dei turni: i turni di prova servono solo a chi non ne ha.')
            else:
                genera_turni_prova(dip, capo=azione == 'turni_prova_capo')
                messages.success(request, f'Turni di prova creati per {dip.nome_breve} (questa settimana e la prossima).')
            return redirect('turni:dipendenti')
        if azione == 'elimina':
            nome, utente = dip.nome_breve, dip.utente
            dip.delete()  # con lui spariscono turni, pulizie e richieste
            if utente and not (utente.is_staff or utente.is_superuser):
                utente.delete()
            messages.success(request, f'{nome} eliminato.')
            return redirect('turni:dipendenti')
        if azione == 'pin':
            return _consegna_credenziali(request, [dip])
        elif azione == 'attivo':
            dip.attivo = not dip.attivo
            dip.save(update_fields=['attivo'])
            if dip.utente:
                dip.utente.is_active = dip.attivo
                dip.utente.save(update_fields=['is_active'])
        return redirect('turni:dipendenti')
    elenco = Dipendente.objects.select_related('utente').annotate(n_turni=Count('turni')).order_by('-attivo', 'nome')
    from .models import Mansione

    return render(
        request,
        'turni/ufficio_dipendenti.html',
        {
            'elenco': elenco,
            'mansioni': Mansione.choices,
            'senza_accesso': Dipendente.objects.filter(attivo=True, utente__isnull=True).count(),
            'email_ok': accessi.email_configurata(),
        },
    )


def _indirizzo_app(request):
    return request.build_absolute_uri(reverse('turni:login'))


def _consegna_credenziali(request, dipendenti):
    """Genera i PIN, li manda all'ufficio turni e mostra le tessere UNA volta sola."""
    credenziali = []
    for dip in dipendenti:
        username, pin = accessi.crea_credenziali(dip)
        credenziali.append({'nome': dip.nome_breve, 'username': username, 'pin': pin})
    inviata = accessi.invia_all_ufficio(credenziali, _indirizzo_app(request))
    request.session['credenziali'] = {'elenco': credenziali, 'email': inviata}
    return redirect('turni:credenziali')


@staff_member_required
def credenziali(request):
    """Tessere stampabili: nome, nome utente, PIN e QR che apre l'app con il nome già scritto.
    I PIN non sono salvati da nessuna parte: ricaricando la pagina spariscono."""
    dati = request.session.pop('credenziali', None)
    if not dati:
        return redirect('turni:dipendenti')
    base = _indirizzo_app(request)
    for c in dati['elenco']:
        c['link'] = f"{base}?u={c['username']}"
        c['qr'] = accessi.qr_svg(c['link'])
    risposta = render(
        request,
        'turni/ufficio_credenziali.html',
        {'credenziali': dati['elenco'], 'email_inviata': dati['email'], 'email_ok': accessi.email_configurata(),
         'ufficio_email': getattr(settings, 'UFFICIO_TURNI_EMAIL', '')},
    )
    risposta['Cache-Control'] = 'no-store'  # il browser non deve conservare la pagina con i PIN
    return risposta


# ---------------------------------------------------------------- app installabile


def manifest(request):
    from django.http import JsonResponse
    from django.templatetags.static import static

    return JsonResponse(
        {
            'name': 'Sarco 4.0',
            'short_name': 'Sarco 4.0',
            'start_url': '/turni/',
            'scope': '/',
            'display': 'standalone',
            'background_color': '#00384f',
            'theme_color': '#00384f',
            # logo Sarco su fondo blu; la versione «tonda» ha più margine per le icone rotonde di Android
            'icons': [
                {'src': static('turni/app-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any'},
                {'src': static('turni/app-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any'},
                {'src': static('turni/app-tonda-192.png'), 'sizes': '192x192', 'type': 'image/png', 'purpose': 'maskable'},
                {'src': static('turni/app-tonda-512.png'), 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
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
  try { d = e.data.json(); } catch (err) { d = { titolo: 'Sarco 4.0', testo: e.data ? e.data.text() : '' }; }
  e.waitUntil(self.registration.showNotification(d.titolo || 'Sarco 4.0', {
    body: d.testo || '', icon: '/static/turni/app-192.png', badge: '/static/turni/app-192.png',
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


@login_required
def archivio_analisi(request):
    """Archivio: le analisi degli ultimi 60 giorni, per giorno."""
    from itertools import groupby

    from .models import AnalisiProdotto

    da = timezone.localdate() - timedelta(days=60)
    analisi = AnalisiProdotto.objects.filter(data__gte=da).order_by('-data', '-pk')
    giorni = [(g, list(r)) for g, r in groupby(analisi, key=lambda a: a.data)]
    return render(request, 'turni/archivio_analisi.html', {'giorni': giorni})

