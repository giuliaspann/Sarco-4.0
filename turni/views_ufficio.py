"""Le pagine dell'ufficio rifatte (Giulia, 11/11/2026): Richieste, Turni, Gestione accessi, Anagrafica."""

from datetime import date, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateformat import format as formatta

from . import accessi, push, saldi
from . import richieste as svc
from .models import (FASCE_LAVORATIVE, AvvisoAssenza, CambioTurno, Dipendente, Disponibilita, Fascia, ModificaTurno, Postazione,
                     RichiestaFerie, RuoloApp, TurnoExtra)

# ---------------------------------------------------------------- Richieste


def _serve_responsabile(request):
    if not svc.e_responsabile(request.user):
        raise PermissionDenied


def _g(d):
    return formatta(d, 'D j/m').capitalize()


def _voce(tipo, oggetto):
    """Una riga della lista: chi chiede, cosa chiede, quando, e lo stato."""
    if tipo == 'cambio':
        c = oggetto
        cosa = 'Cambio turno · ' + ' e '.join(_g(g) for g in c.giorni)
        chi = f'{c.richiedente.nome_breve} ↔ {c.collega.nome_breve}'
        aperta = c.stato == CambioTurno.Stato.ATTESA_UFFICIO
        quando, stato = c.gestito_il or c.risposta_collega_il or c.creato_il, c.get_stato_display()
        ok = c.stato == CambioTurno.Stato.APPROVATO
    elif tipo == 'ferie':
        f = oggetto
        periodo = _g(f.dal) if f.dal == f.al else f'{_g(f.dal)} – {_g(f.al)}'
        if f.a_ore:
            periodo += f' · {f.dalle:%H:%M}–{f.alle:%H:%M}'
        cosa, chi = f'{f.get_tipo_display()} · {periodo}', f.dipendente.nome_breve
        aperta = f.stato == RichiestaFerie.Stato.ATTESA
        quando, stato = f.gestita_il or f.creata_il, f.get_stato_display()
        ok = f.stato == RichiestaFerie.Stato.APPROVATA
    else:
        a = oggetto
        cosa = f'{a.get_tipo_display()} · {_g(a.data)}' + (f' · {a.orario}' if a.orario else '')
        chi = a.dipendente.nome_breve
        aperta = not a.esito and not a.annullato_il
        quando = a.visto_il or a.creato_il
        stato = 'Annullato' if a.annullato_il else {'approvato': 'Approvato', 'rifiutato': 'Rifiutato'}.get(a.esito, 'Da convalidare')
        ok = a.esito == 'approvato'
    return {'tipo': tipo, 'pk': oggetto.pk, 'chi': chi, 'cosa': cosa, 'aperta': aperta, 'quando': quando,
            'stato': stato, 'ok': ok}


def _oggetto(tipo, pk):
    if tipo == 'cambio':
        return get_object_or_404(CambioTurno.objects.select_related('richiedente', 'collega'), pk=pk)
    if tipo == 'ferie':
        return get_object_or_404(RichiestaFerie.objects.select_related('dipendente'), pk=pk)
    if tipo == 'avviso':
        return get_object_or_404(AvvisoAssenza.objects.select_related('dipendente'), pk=pk)
    raise Http404


@login_required
def richieste(request):
    """In alto le richieste da approvare, sotto quelle risolte: una riga per richiesta, Approva / Rifiuta a fianco."""
    _serve_responsabile(request)
    aperte = [_voce('cambio', c) for c in CambioTurno.objects.filter(stato=CambioTurno.Stato.ATTESA_UFFICIO).select_related('richiedente', 'collega')]
    aperte += [_voce('ferie', f) for f in RichiestaFerie.objects.filter(stato=RichiestaFerie.Stato.ATTESA).select_related('dipendente')]
    aperte += [_voce('avviso', a) for a in AvvisoAssenza.objects.filter(esito='', annullato_il__isnull=True).select_related('dipendente')]
    aperte.sort(key=lambda v: v['quando'])
    risolte = [_voce('cambio', c) for c in CambioTurno.objects.exclude(stato__in=CambioTurno.IN_CORSO).select_related('richiedente', 'collega')[:30]]
    risolte += [_voce('ferie', f) for f in RichiestaFerie.objects.exclude(stato=RichiestaFerie.Stato.ATTESA).select_related('dipendente')[:30]]
    risolte += [_voce('avviso', a) for a in AvvisoAssenza.objects.exclude(esito='', annullato_il__isnull=True).select_related('dipendente')[:30]]
    risolte.sort(key=lambda v: v['quando'], reverse=True)
    return render(request, 'turni/uff_richieste.html', {'aperte': aperte, 'risolte': risolte[:40]})


@login_required
def richiesta(request, tipo, pk):
    """Il dettaglio di una richiesta, con Approva / Rifiuta se è ancora da decidere."""
    from .views_richieste import _righe_cambio

    _serve_responsabile(request)
    o = _oggetto(tipo, pk)
    contesto = {'v': _voce(tipo, o), 'o': o, 'tipo': tipo}
    if tipo == 'cambio':
        contesto['persone'] = [(o.richiedente, _righe_cambio(o, o.richiedente)), (o.collega, _righe_cambio(o, o.collega))]
    elif tipo == 'ferie':
        contesto['colleghi_assenti'] = (RichiestaFerie.objects.filter(stato=RichiestaFerie.Stato.APPROVATA, dal__lte=o.al, al__gte=o.dal)
                                        .exclude(dipendente=o.dipendente).select_related('dipendente'))
        contesto['turni'] = [t for t in o.dipendente.turni.filter(data__range=(o.dal, o.al)) if t.lavora]
    return render(request, 'turni/uff_richiesta.html', contesto)


@login_required
def richiesta_scelta(request, tipo, pk, scelta):
    """Approva / Rifiuta: prima si chiede di convalidare la scelta, poi si esegue."""
    _serve_responsabile(request)
    if scelta not in ('approva', 'rifiuta'):
        raise Http404
    o = _oggetto(tipo, pk)
    v = _voce(tipo, o)
    approva = scelta == 'approva'
    if not v['aperta']:
        messages.info(request, 'Questa richiesta è già stata decisa.')
        return redirect('turni:ufficio_richieste')
    if request.method == 'POST':
        nota = (request.POST.get('nota') or '').strip()[:300]
        try:
            if tipo == 'cambio':
                svc.decisione_ufficio_cambio(o, request.user, approva, nota)
            elif tipo == 'ferie':
                svc.decisione_ufficio_ferie(o, request.user, approva, nota)
            else:
                o.esito = 'approvato' if approva else 'rifiutato'
                o.visto_da, o.visto_il, o.nota_ufficio = request.user, timezone.now(), nota
                o.save(update_fields=['esito', 'visto_da', 'visto_il', 'nota_ufficio'])
                if o.dipendente.utente_id:
                    push.invia([o.dipendente.utente_id], f'{o.get_tipo_display()} {"approvato" if approva else "non approvato"}',
                               f'{_g(o.data)}' + (f' · {nota}' if nota else ''), reverse('turni:archivio_richieste'),
                               mittente=request.user)
        except svc.RichiestaNonValida as e:
            messages.error(request, str(e))
        else:
            messages.success(request, f'{v["cosa"]} di {v["chi"]}: {"approvata" if approva else "rifiutata"}.')
        return redirect('turni:ufficio_richieste')
    return render(request, 'turni/uff_richiesta_scelta.html', {'v': v, 'approva': approva, 'tipo': tipo, 'pk': pk})


# ---------------------------------------------------------------- Turni


@login_required
def turni(request):
    """Due tasti: Carica turni della settimana e Richiedi turno extra; sotto la presa visione dei turni cambiati."""
    if not (request.user.is_staff or svc.e_responsabile(request.user)):
        raise PermissionDenied
    oggi = timezone.localdate()
    extra = list(TurnoExtra.objects.filter(data__gte=oggi, chiusa=False).prefetch_related('disponibilita__dipendente'))
    modifiche = (ModificaTurno.objects.filter(creata_il__gte=timezone.now() - timedelta(days=14))
                 .select_related('dipendente').order_by('vista_il', '-creata_il')[:60])
    return render(request, 'turni/uff_turni.html', {'extra': extra, 'modifiche': modifiche})


@login_required
def extra_nuovo(request):
    """Richiedi turno extra: quando, quale turno, quale area e chi serve. Tutti gli operai ricevono la notifica."""
    if not (request.user.is_staff or svc.e_responsabile(request.user)):
        raise PermissionDenied
    oggi = timezone.localdate()
    fasce = TurnoExtra._meta.get_field('fascia').choices
    ruoli = TurnoExtra._meta.get_field('ruolo').choices
    if request.method == 'POST':
        try:
            giorno = date.fromisoformat(request.POST.get('data') or '')
        except ValueError:
            giorno = None
        fascia = request.POST.get('fascia')
        postazione = request.POST.get('postazione', '')
        ruolo = request.POST.get('ruolo', '')
        try:
            posti = max(1, min(20, int(request.POST.get('posti') or 1)))
        except ValueError:
            posti = 1
        if not giorno or giorno < oggi or fascia not in dict(fasce):
            messages.error(request, 'Scegli un giorno da oggi in poi e il turno.')
        else:
            e = TurnoExtra.objects.create(
                data=giorno, fascia=fascia, postazione=postazione if postazione in Postazione.values else '',
                ruolo=ruolo if ruolo in dict(ruoli) else '', posti=posti, nota=(request.POST.get('nota') or '')[:300],
                creata_da=request.user)
            liberi = [d for d in Dipendente.objects.filter(attivo=True, utente__isnull=False)
                      if svc.ha_mansione(d, e.ruolo) and not d.turni.filter(data=giorno, fascia__in=list(FASCE_LAVORATIVE)).exists()]
            push.invia([d.utente_id for d in liberi], 'Cercasi turno extra',
                       f'{_g(giorno)} · {e.get_fascia_display()}' + (f' · {e.get_postazione_display()}' if e.postazione else '')
                       + f' · servono {posti}', reverse('turni:miei_turni'), mittente=request.user)
            messages.success(request, f'Richiesta inviata a {len(liberi)} operai: chi è disponibile lo conferma dall\'app.')
            return redirect('turni:ufficio_turni')
    return render(request, 'turni/uff_extra_nuovo.html', {
        'fasce': fasce, 'ruoli': [r for r in ruoli if r[0]], 'postazioni': Postazione.choices, 'oggi': oggi.isoformat(),
    })


# ---------------------------------------------------------------- Gestione accessi


@login_required
def accessi_view(request):
    """«Attiva accesso» e «Disattiva accesso», ognuno con la scelta del nome (e del ruolo per l'attivazione)."""
    if not request.user.is_staff:
        raise PermissionDenied
    if request.method == 'POST':
        azione = request.POST.get('azione')
        if azione == 'elenco':
            # l'elenco dei dipendenti dal file «Organizzazione Turni», foglio «Elenco Dipendenti, Aree e Orari»
            from . import importa
            f = request.FILES.get('file')
            if not f or not f.name.lower().endswith(('.xlsx', '.xlsm')) or f.size > 5 * 1024 * 1024:
                messages.error(request, 'Carica il file Excel «Organizzazione Turni» (.xlsx, massimo 5 MB).')
            else:
                try:
                    nuovi, presenti = importa.aggiorna_elenco_dipendenti(importa.leggi_elenco_dipendenti(f))
                except Exception as e:  # file rovinato o foglio mancante: lo dico com'è
                    messages.error(request, f'Non riesco a leggere il file: {e}')
                else:
                    messages.success(request, f'Elenco aggiornato: {len(nuovi)} nuovi dipendenti, {len(presenti)} già presenti.')
            return redirect('turni:accessi')
        if azione == 'tutti':
            senza = list(Dipendente.objects.filter(attivo=True).filter(Q(utente__isnull=True) | Q(utente__is_active=False)).order_by('nome'))
            if not senza:
                messages.info(request, "Tutti i dipendenti hanno già l'accesso.")
                return redirect('turni:accessi')
            from .views import _consegna_credenziali
            return _consegna_credenziali(request, senza)  # le tessere di tutti, una volta sola
        dip = get_object_or_404(Dipendente, pk=request.POST.get('dipendente') or 0)
        if azione == 'attiva':
            from .accessi import RUOLI_ACCESSO, imposta_ruolo

            ruolo = request.POST.get('ruolo')
            if ruolo in dict(RUOLI_ACCESSO):
                imposta_ruolo(dip, ruolo, request.POST.get('ufficio', ''))
            dip.attivo = True
            dip.save(update_fields=['attivo'])
            from .views import _consegna_credenziali
            return _consegna_credenziali(request, [dip])  # la tessera con nome utente e PIN, una volta sola
        if dip.utente:
            dip.utente.is_active = False
            dip.utente.save(update_fields=['is_active'])
            messages.success(request, f'Accesso di {dip.nome_breve} disattivato: lo storico resta.')
        return redirect('turni:accessi')
    tutti = list(Dipendente.objects.filter(attivo=True).select_related('utente').order_by('nome'))
    return render(request, 'turni/uff_accessi.html', {
        'da_attivare': [d for d in tutti if not d.utente or not d.utente.is_active],
        'attivi': [d for d in tutti if d.utente and d.utente.is_active],
        'tutti': tutti,
        'ruoli': __import__('turni.accessi', fromlist=['RUOLI_ACCESSO']).RUOLI_ACCESSO,
        'uffici': __import__('turni.accessi', fromlist=['UFFICI']).UFFICI,
    })


# ---------------------------------------------------------------- Anagrafica


def _pct(parte, totale):
    return f'{Decimal(parte) * 100 / Decimal(totale):.1f} %'.replace('.', ',') if totale else '—'


def scheda_anagrafica(dip):
    """Dati e indici dall'inizio dell'anno (i turni fino a oggi)."""
    oggi = timezone.localdate()
    inizio = oggi.replace(month=1, day=1)
    turni_anno = list(dip.turni.filter(data__range=(inizio, oggi)))
    lavorati = [t for t in turni_anno if t.fascia in FASCE_LAVORATIVE]
    notti = sum(1 for t in lavorati if t.fascia == Fascia.NOTTE)
    giorni_ferie = sum(1 for t in turni_anno if t.fascia == Fascia.FERIE)
    giorni_permesso = sum(1 for t in turni_anno if t.fascia == Fascia.PERMESSO)
    rol = [r for r in dip.richieste_ferie.filter(tipo=RichiestaFerie.Tipo.PERMESSO, stato=RichiestaFerie.Stato.APPROVATA,
                                                  dal__range=(inizio, oggi))]
    ore_rol = sum((saldi.ore_richiesta(r) for r in rol), Decimal('0'))
    avvisi = dip.avvisi.filter(data__range=(inizio, oggi), annullato_il__isnull=True).exclude(esito='rifiutato')
    ritardi = avvisi.filter(tipo=AvvisoAssenza.Tipo.RITARDO).count()
    uscite = avvisi.filter(tipo=AvvisoAssenza.Tipo.USCITA).count()
    malattia = avvisi.filter(tipo=AvvisoAssenza.Tipo.MALATTIA).count()
    richieste_extra = TurnoExtra.objects.filter(data__range=(inizio, oggi)).count()
    offerte = Disponibilita.objects.filter(dipendente=dip, extra__data__range=(inizio, oggi)).count()
    residuo = saldi.residuo(dip)
    n = len(lavorati)
    ore_lavoro = n * saldi.ORE_GIORNO
    ore = lambda x: f'{x:.1f} h'.replace('.', ',').replace(',0 h', ' h')  # noqa: E731
    dati = [
        ('Data di nascita', f'{dip.data_nascita:%d/%m/%Y}' if dip.data_nascita else '—'),
        ('Data di assunzione', f'{dip.data_assunzione:%d/%m/%Y}' if dip.data_assunzione else '—'),
        ('Ruolo', ' · '.join(x for x in [dip.qualifica or dip.mansioni_display, dip.get_ruolo_app_display()] if x)),
    ]
    numeri = [
        ('Ferie residue', f'{residuo["ferie_giorni"]:.1f} g'.replace('.', ',') if residuo else 'saldo non caricato'),
        ('ROL residui', ore(residuo['rol']) if residuo else 'saldo non caricato'),
        ('Giorni di ferie usati', giorni_ferie),
        ('Ore di ROL usate', ore(ore_rol)),
        ('Giorni di malattia', malattia),
        ('Permessi', giorni_permesso),
        ('Ritardi', ritardi),
        ('Uscite anticipate', uscite),
    ]
    indici = [
        ('Adesione ai turni extra', _pct(offerte, richieste_extra)),
        ('Turni notturni', _pct(notti, n)),
        ('Ferie su giorni lavorativi', _pct(giorni_ferie, n + giorni_ferie)),
        ('ROL su ore lavorative', _pct(ore_rol, ore_lavoro)),
        ('Ritardi su ingressi', _pct(ritardi, n)),
        ('Uscite anticipate su ingressi', _pct(uscite, n)),
    ]
    return {'dati': dati, 'numeri': numeri, 'indici': indici, 'dal': inizio, 'al': oggi, 'turni_lavorati': n}


@login_required
def anagrafica(request):
    if not request.user.is_staff:
        raise PermissionDenied
    elenco = Dipendente.objects.filter(attivo=True).order_by('nome')
    dip = elenco.filter(pk=request.GET.get('dip') or 0).first() if (request.GET.get('dip') or '').isdigit() else None
    if request.method == 'POST' and dip:
        for campo in ('data_nascita', 'data_assunzione'):
            try:
                setattr(dip, campo, date.fromisoformat(request.POST.get(campo)) if request.POST.get(campo) else None)
            except ValueError:
                messages.error(request, 'Una delle date non è valida.')
                return redirect(f'{reverse("turni:anagrafica")}?dip={dip.pk}')
        dip.save(update_fields=['data_nascita', 'data_assunzione'])
        messages.success(request, 'Dati salvati.')
        return redirect(f'{reverse("turni:anagrafica")}?dip={dip.pk}')
    return render(request, 'turni/uff_anagrafica.html', {'elenco': elenco, 'dip': dip, 's': scheda_anagrafica(dip) if dip else None})


@login_required
def anagrafica_pdf(request, dip_id):
    if not request.user.is_staff:
        raise PermissionDenied
    from .pdf import Documento
    from .views_archivio import _intestazione

    dip = get_object_or_404(Dipendente, pk=dip_id)
    s = scheda_anagrafica(dip)
    doc = Documento(f'Anagrafica {dip.nome_breve}')
    _intestazione(doc, dip.nome_breve, f'Anagrafica · dal {s["dal"]:%d/%m/%Y} al {s["al"]:%d/%m/%Y} · {s["turni_lavorati"]} turni lavorati',
                  request.user)
    for titolo, righe in (('Dati', s['dati']), ('Presenze e assenze', s['numeri']), ('Indici', s['indici'])):
        doc.testo(titolo, 12, True, (0.05, 0.2, 0.3))
        for e, v in righe:
            doc.voce(e, v)
        doc.linea()
    risposta = HttpResponse(doc.pdf(), content_type='application/pdf')
    risposta['Content-Disposition'] = f'attachment; filename="Anagrafica {dip.nome_breve}.pdf"'
    return risposta
