"""Messaggi: Bacheca (scrive l'ufficio) e Chat di gruppo (scrivono tutti), con notifiche."""

import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_POST

from . import push
from .models import Annuncio, IscrizionePush, MessaggioChat, StatoMessaggi
from .richieste import e_responsabile

MESSAGGI_MOSTRATI = 100


def nome_di(utente):
    dip = getattr(utente, 'dipendente', None)
    if dip:
        return dip.nome_breve
    if e_responsabile(utente) or utente.is_staff:
        return 'Ufficio Turni'
    return utente.get_full_name() or utente.username


def stato_di(utente):
    stato, _ = StatoMessaggi.objects.get_or_create(utente=utente)
    return stato


def destinatari(escluso, solo_chat=False):
    """Utenti attivi che ricevono la notifica (chi scrive escluso)."""
    utenti = get_user_model().objects.filter(is_active=True).exclude(pk=escluso.pk)
    if solo_chat:
        utenti = utenti.exclude(stato_messaggi__notifiche_chat=False)
    return utenti.values_list('pk', flat=True)


def etichetta_giorno(giorno):
    """Separatore come su WhatsApp: Oggi, Ieri, giorno della settimana o data."""
    oggi = timezone.localdate()
    if giorno == oggi:
        return 'Oggi'
    if giorno == oggi - timedelta(days=1):
        return 'Ieri'
    if (oggi - giorno).days < 7:
        return date_format(giorno, 'l').capitalize()
    return date_format(giorno, 'j F Y')


def _messaggio_json(m, utente, responsabile):
    quando = timezone.localtime(m.creato_il)
    return {
        'id': m.pk,
        'autore': nome_di(m.autore),
        'autore_id': m.autore_id,
        # colore del nome, fisso per persona (come i gruppi WhatsApp)
        'colore': m.autore_id % 8,
        'mio': m.autore_id == utente.pk,
        'ufficio': getattr(m.autore, 'dipendente', None) is None,
        'testo': '' if m.eliminato else m.testo,
        'eliminato': m.eliminato,
        'giorno': quando.date().isoformat(),
        'etichetta_giorno': etichetta_giorno(quando.date()),
        'ora': quando.strftime('%H:%M'),
        'eliminabile': not m.eliminato and (m.autore_id == utente.pk or responsabile),
    }


def con_gruppi(messaggi):
    """Segna dove serve il separatore di data e dove inizia un gruppo di messaggi della stessa persona."""
    precedente = None
    for m in messaggi:
        m['nuovo_giorno'] = precedente is None or precedente['giorno'] != m['giorno']
        m['primo'] = m['nuovo_giorno'] or precedente['autore_id'] != m['autore_id']
        precedente = m
    return messaggi


@login_required
def messaggi(request):
    vista = request.GET.get('vista') or request.POST.get('vista') or 'chat'
    responsabile = e_responsabile(request.user)
    stato = stato_di(request.user)

    if request.method == 'POST':
        azione = request.POST.get('azione')
        testo = (request.POST.get('testo') or '').strip()
        if azione == 'annuncio' and responsabile and testo:
            a = Annuncio.objects.create(
                testo=testo[:2000], importante=bool(request.POST.get('importante')), autore=request.user
            )
            push.invia(
                destinatari(request.user),
                'Bacheca Sarco' if not a.importante else 'Avviso importante',
                a.testo,
                reverse('turni:messaggi') + '?vista=bacheca',
            )
            messages.success(request, 'Avviso pubblicato in bacheca.')
        elif azione == 'elimina_annuncio' and responsabile:
            get_object_or_404(Annuncio, pk=request.POST.get('annuncio')).delete()
        elif azione == 'chat' and testo and MessaggioChat.objects.filter(
            autore=request.user, creato_il__gte=timezone.now() - timedelta(minutes=1)
        ).count() >= 10:
            messages.error(request, 'Stai scrivendo troppi messaggi di seguito: aspetta un minuto.')
        elif azione == 'chat' and testo:
            m = MessaggioChat.objects.create(autore=request.user, testo=testo[:1000])
            push.invia(destinatari(request.user, solo_chat=True), f'Chat · {nome_di(request.user)}', m.testo,
                       reverse('turni:messaggi') + '?vista=chat')
        elif azione == 'elimina_chat':
            m = get_object_or_404(MessaggioChat, pk=request.POST.get('messaggio'))
            if m.autore_id == request.user.pk or responsabile:
                m.eliminato = True
                m.save(update_fields=['eliminato'])
        elif azione == 'notifiche_chat':
            stato.notifiche_chat = not stato.notifiche_chat
            stato.save(update_fields=['notifiche_chat'])
        return redirect(f"{reverse('turni:messaggi')}?vista={vista}" + ('#fondo' if vista == 'chat' else ''))

    contesto = {'vista': vista, 'responsabile': responsabile, 'stato': stato, 'chiave_push': push.chiavi().pubblica}
    if vista == 'bacheca':
        recenti = list(Annuncio.objects.select_related('autore').order_by('-creato_il')[:50])[::-1]
        precedente = None
        for a in recenti:
            giorno = timezone.localtime(a.creato_il).date()
            a.nuovo_giorno = giorno != precedente
            a.etichetta_giorno = etichetta_giorno(giorno)
            precedente = giorno
        contesto['annunci'] = recenti
        contesto['membri'] = get_user_model().objects.filter(is_active=True).count()
        stato.bacheca_letta_il = timezone.now()
        stato.save(update_fields=['bacheca_letta_il'])
    else:
        ultimi = list(
            MessaggioChat.objects.select_related('autore', 'autore__dipendente').order_by('-pk')[:MESSAGGI_MOSTRATI]
        )[::-1]
        contesto['chat'] = con_gruppi([_messaggio_json(m, request.user, responsabile) for m in ultimi])
        contesto['membri'] = get_user_model().objects.filter(is_active=True).count()
        contesto['ultimo_id'] = ultimi[-1].pk if ultimi else 0
        if ultimi:
            stato.chat_letta_fino = ultimi[-1].pk
            stato.save(update_fields=['chat_letta_fino'])
    contesto['bacheca_nuovi'] = non_letti_bacheca(request.user, stato)
    contesto['chat_nuovi'] = non_letti_chat(request.user, stato)
    return render(request, 'turni/messaggi.html', contesto)


@login_required
def chat_nuovi(request):
    """Aggiornamento automatico della chat aperta (ogni pochi secondi)."""
    try:
        dopo = int(request.GET.get('dopo', 0))
    except ValueError:
        return HttpResponseBadRequest()
    responsabile = e_responsabile(request.user)
    nuovi = list(MessaggioChat.objects.filter(pk__gt=dopo).select_related('autore', 'autore__dipendente')[:50])
    if nuovi:
        stato = stato_di(request.user)
        stato.chat_letta_fino = max(stato.chat_letta_fino, nuovi[-1].pk)
        stato.save(update_fields=['chat_letta_fino'])
    return JsonResponse({'messaggi': [_messaggio_json(m, request.user, responsabile) for m in nuovi]})


@login_required
@require_POST
def iscrivi_notifiche(request):
    try:
        dati = json.loads(request.body)
        endpoint, chiavi = dati['endpoint'], dati['keys']
        from .sicurezza import endpoint_push_valido

        if not endpoint_push_valido(endpoint) or len(str(chiavi['p256dh'])) > 200 or len(str(chiavi['auth'])) > 100:
            return HttpResponseBadRequest()
        IscrizionePush.objects.update_or_create(
            endpoint=endpoint,
            defaults={'utente': request.user, 'p256dh': chiavi['p256dh'], 'auth': chiavi['auth']},
        )
    except (ValueError, KeyError, TypeError):
        return HttpResponseBadRequest()
    return JsonResponse({'ok': True})


def non_letti_bacheca(utente, stato=None):
    stato = stato or stato_di(utente)
    qs = Annuncio.objects.exclude(autore=utente)
    if stato.bacheca_letta_il:
        qs = qs.filter(creato_il__gt=stato.bacheca_letta_il)
    return qs.count()


def non_letti_chat(utente, stato=None):
    stato = stato or stato_di(utente)
    return MessaggioChat.objects.filter(pk__gt=stato.chat_letta_fino, eliminato=False).exclude(autore=utente).count()
