"""Riunioni in ufficio (Giulia, 10/11/2026).

L'ufficio (o un responsabile) programma la riunione: titolo, giorno, orario, luogo e chi invitare.
Ogni invitato riceve una notifica con Conferma / Rifiuta; chi l'ha programmata viene avvisato delle risposte.
La riunione compare come riquadro, tipo calendario, nella settimana dei turni ("I miei turni").
"""

from datetime import date, datetime, time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from . import push
from .models import Dipendente, InvitoRiunione, Riunione


def puo_programmare_riunione(utente):
    from .richieste import e_responsabile

    dip = getattr(utente, 'dipendente', None)
    return bool(utente.is_authenticated and (
        utente.is_staff or e_responsabile(utente)
        or (dip and (dip.resp_impianto or dip.resp_piazzale or dip.resp_manutenzione))))


def quando(r):
    """'Gio 12/11 · 10:00–11:00'"""
    from django.utils.dateformat import format as formatta

    i, f = timezone.localtime(r.inizio), timezone.localtime(r.fine)
    return f'{formatta(i, "D d/m").capitalize()} · {i:%H:%M}–{f:%H:%M}'


def mio_invito(utente, riunione):
    dip = getattr(utente, 'dipendente', None)
    return riunione.inviti.filter(dipendente=dip).first() if dip else None


def puo_rispondere(invito, utente):
    return bool(invito and invito.dipendente.utente_id == utente.pk and not invito.riunione.annullata
                and invito.riunione.fine > timezone.now() and invito.risposta == InvitoRiunione.Risposta.ATTESA)


def rispondi(invito, partecipa):
    invito.risposta = InvitoRiunione.Risposta.SI if partecipa else InvitoRiunione.Risposta.NO
    invito.risposto_il = timezone.now()
    invito.save(update_fields=['risposta', 'risposto_il'])
    r = invito.riunione
    if r.creata_da_id and r.creata_da_id != invito.dipendente.utente_id:
        push.invia([r.creata_da_id], f'{invito.dipendente.nome_breve} {"partecipa" if partecipa else "non partecipa"}',
                   f'{r.titolo} · {quando(r)}', reverse('turni:riunione', args=[r.pk]), mittente=invito.dipendente.utente)


def riunioni_della_settimana(dip, inizio, fine):
    """Le riunioni a cui è invitato (e non ha detto di no), giorno per giorno."""
    if dip is None:
        return []
    inviti = (InvitoRiunione.objects.filter(dipendente=dip, riunione__annullata=False,
                                            riunione__inizio__date__range=(inizio, fine))
              .exclude(risposta=InvitoRiunione.Risposta.NO).select_related('riunione').order_by('riunione__inizio'))
    return list(inviti)


@login_required
def elenco(request):
    if not puo_programmare_riunione(request.user):
        raise PermissionDenied
    adesso = timezone.now()
    prossime = Riunione.objects.filter(fine__gte=adesso).prefetch_related('inviti')
    passate = Riunione.objects.filter(fine__lt=adesso).order_by('-inizio')[:10]
    return render(request, 'turni/riunioni.html', {'prossime': prossime, 'passate': passate})


def _ora(testo, predefinita):
    try:
        return time.fromisoformat(testo) if testo else predefinita
    except ValueError:
        return None


@login_required
def nuova(request):
    if not puo_programmare_riunione(request.user):
        raise PermissionDenied
    dipendenti = Dipendente.objects.filter(attivo=True, utente__isnull=False).order_by('nome')
    if request.method == 'POST':
        p = request.POST
        titolo = (p.get('titolo') or '').strip()[:120]
        luogo = (p.get('luogo') or '').strip()[:80] or 'Ufficio'
        note = (p.get('note') or '').strip()[:2000]
        try:
            giorno = date.fromisoformat(p.get('giorno') or '')
        except ValueError:
            giorno = None
        dalle, alle = _ora(p.get('dalle'), None), _ora(p.get('alle'), None)
        scelti = list(dipendenti.filter(pk__in=[x for x in p.getlist('invitati') if x.isdigit()]))
        errore = ''
        if not titolo:
            errore = 'Scrivi il titolo della riunione.'
        elif not giorno or giorno < timezone.localdate():
            errore = 'Scegli il giorno (da oggi in poi).'
        elif not dalle or not alle or alle <= dalle:
            errore = "Scegli l'orario: l'ora di fine deve venire dopo l'inizio."
        elif not scelti:
            errore = 'Scegli almeno una persona da invitare.'
        if errore:
            messages.error(request, errore)
        else:
            r = Riunione.objects.create(
                titolo=titolo, luogo=luogo, note=note, creata_da=request.user,
                inizio=timezone.make_aware(datetime.combine(giorno, dalle)),
                fine=timezone.make_aware(datetime.combine(giorno, alle)))
            for d in scelti:
                inv = InvitoRiunione.objects.create(riunione=r, dipendente=d)
                push.invia([d.utente_id], f'Riunione: {titolo}', f'{quando(r)} · {luogo}',
                           reverse('turni:riunione', args=[r.pk]), mittente=request.user, tipo='riunione', oggetto_id=inv.pk)
            messages.success(request, f'Riunione programmata: {len(scelti)} invitati, ognuno deve confermare la partecipazione.')
            return redirect('turni:riunione', r.pk)
    return render(request, 'turni/riunione_nuova.html', {
        'dipendenti': dipendenti, 'oggi': timezone.localdate().isoformat(),
        'scelti': set(request.POST.getlist('invitati')),
    })


@login_required
def dettaglio(request, riunione_id):
    r = get_object_or_404(Riunione.objects.select_related('creata_da'), pk=riunione_id)
    organizza = puo_programmare_riunione(request.user)
    invito = mio_invito(request.user, r)
    if not organizza and invito is None:
        raise PermissionDenied
    if request.method == 'POST':
        azione = request.POST.get('azione')
        if azione in ('si', 'no') and invito and not r.annullata and r.fine > timezone.now():
            rispondi(invito, azione == 'si')
            from .models import Notifica
            Notifica.objects.filter(utente=request.user, tipo='riunione', oggetto_id=invito.pk).update(
                esito='confermata' if azione == 'si' else 'rifiutata')
            messages.success(request, 'Partecipazione confermata.' if azione == 'si' else 'Hai detto che non partecipi.')
        elif azione == 'annulla' and organizza and not r.annullata:
            r.annullata = True
            r.save(update_fields=['annullata'])
            ids = [i.dipendente.utente_id for i in r.inviti.select_related('dipendente').exclude(risposta=InvitoRiunione.Risposta.NO)]
            push.invia(ids, f'Riunione annullata: {r.titolo}', quando(r), reverse('turni:riunione', args=[r.pk]), mittente=request.user)
            messages.success(request, 'Riunione annullata: gli invitati sono stati avvisati.')
        return redirect('turni:riunione', r.pk)
    inviti = list(r.inviti.select_related('dipendente').order_by('dipendente__nome'))
    conta = {nome: sum(1 for i in inviti if i.risposta == k) for nome, k in (('si', 'si'), ('no', 'no'), ('attesa', ''))}
    return render(request, 'turni/riunione.html', {
        'r': r, 'quando': quando(r), 'invito': invito, 'organizza': organizza, 'inviti': inviti, 'conta': conta,
        'finita': r.fine <= timezone.now(),
    })
