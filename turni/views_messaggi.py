"""Messaggi: Bacheca (scrive l'ufficio) e più chat di gruppo, con notifiche.

Le chat sono lo storico dell'azienda: un messaggio "eliminato" sparisce per tutti ma resta
leggibile dalla direzione, che è sempre dentro ogni chat.
"""

import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.http import require_POST

from . import push
from .models import Annuncio, Chat, IscrizionePush, LetturaChat, MessaggioChat, RuoloApp, StatoMessaggi
from .richieste import e_responsabile

MESSAGGI_MOSTRATI = 100


def nome_di(utente):
    dip = getattr(utente, 'dipendente', None)
    if dip:
        return dip.nome_breve
    if e_responsabile(utente) or utente.is_staff:
        return 'Ufficio Turni'
    return utente.get_full_name() or utente.username


def e_direzione(utente):
    dip = getattr(utente, 'dipendente', None)
    return utente.is_superuser or (dip is not None and dip.ruolo_app == RuoloApp.DIREZIONE)


def stato_di(utente):
    stato, _ = StatoMessaggi.objects.get_or_create(utente=utente)
    return stato


def chat_visibili(utente):
    """Chat aperte a tutti, quelle di cui si è membri; la direzione le vede tutte."""
    qs = Chat.objects.all()
    if not e_direzione(utente):
        qs = qs.filter(Q(tutti=True) | Q(membri=utente)).distinct()
    return qs


def membri_di(chat):
    utenti = get_user_model().objects.filter(is_active=True)
    if chat.tutti:
        return utenti
    direzione = Q(dipendente__ruolo_app=RuoloApp.DIREZIONE) | Q(is_superuser=True)
    return utenti.filter(Q(pk__in=chat.membri.values('pk')) | direzione).distinct()


def destinatari(escluso, chat=None):
    """Chi riceve la notifica (chi scrive escluso). Per le chat solo chi non ha spento le notifiche."""
    utenti = (membri_di(chat) if chat else get_user_model().objects.filter(is_active=True)).exclude(pk=escluso.pk)
    if chat:
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


def _messaggio_json(m, utente, responsabile, direzione=False):
    quando = timezone.localtime(m.creato_il)
    return {
        'id': m.pk,
        'autore': nome_di(m.autore),
        'autore_id': m.autore_id,
        # colore del nome, fisso per persona (come i gruppi WhatsApp)
        'colore': m.autore_id % 8,
        'mio': m.autore_id == utente.pk,
        'ufficio': getattr(m.autore, 'dipendente', None) is None,
        # storico: la direzione legge anche i messaggi eliminati
        'testo': m.testo if (not m.eliminato or direzione) else '',
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


def _letta_fino(utente, chat):
    return LetturaChat.objects.filter(utente=utente, chat=chat).values_list('letta_fino', flat=True).first() or 0


def _segna_letta(utente, chat, fino):
    lettura, _ = LetturaChat.objects.get_or_create(utente=utente, chat=chat)
    if fino > lettura.letta_fino:
        lettura.letta_fino = fino
        lettura.save(update_fields=['letta_fino'])


def _url_chat(chat):
    return f"{reverse('turni:messaggi')}?vista=chat&chat={chat.pk}"


@login_required
def messaggi(request):
    vista = request.GET.get('vista') or request.POST.get('vista') or 'lista'
    responsabile = e_responsabile(request.user)
    direzione = e_direzione(request.user)
    stato = stato_di(request.user)
    chat = None
    if vista == 'chat':
        try:
            chat = chat_visibili(request.user).get(pk=request.GET.get('chat') or request.POST.get('chat'))
        except (Chat.DoesNotExist, ValueError):
            return redirect('turni:messaggi')

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
        elif azione == 'chat' and chat and testo and MessaggioChat.objects.filter(
            autore=request.user, creato_il__gte=timezone.now() - timedelta(minutes=1)
        ).count() >= 10:
            messages.error(request, 'Stai scrivendo troppi messaggi di seguito: aspetta un minuto.')
        elif azione == 'chat' and chat and testo:
            m = MessaggioChat.objects.create(chat=chat, autore=request.user, testo=testo[:1000])
            push.invia(destinatari(request.user, chat), f'{chat.nome} · {nome_di(request.user)}', m.testo, _url_chat(chat))
        elif azione == 'elimina_chat' and chat:
            m = get_object_or_404(MessaggioChat, pk=request.POST.get('messaggio'), chat=chat)
            if m.autore_id == request.user.pk or responsabile:
                m.eliminato = True  # resta nello storico per la direzione
                m.save(update_fields=['eliminato'])
        elif azione == 'notifiche_chat':
            stato.notifiche_chat = not stato.notifiche_chat
            stato.save(update_fields=['notifiche_chat'])
        if chat:
            return redirect(_url_chat(chat) + '#fondo')
        return redirect(f"{reverse('turni:messaggi')}?vista={vista}")

    contesto = {
        'vista': vista, 'responsabile': responsabile, 'direzione': direzione, 'stato': stato,
        'chiave_push': push.chiavi().pubblica,
    }
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
    elif chat:
        ultimi = list(
            chat.messaggi.select_related('autore', 'autore__dipendente').order_by('-pk')[:MESSAGGI_MOSTRATI]
        )[::-1]
        contesto['chat_aperta'] = chat
        contesto['chat'] = con_gruppi([_messaggio_json(m, request.user, responsabile, direzione) for m in ultimi])
        contesto['membri'] = membri_di(chat).count()
        contesto['ultimo_id'] = ultimi[-1].pk if ultimi else 0
        if ultimi:
            _segna_letta(request.user, chat, ultimi[-1].pk)
    else:
        contesto['elenco'] = elenco_chat(request.user)
        contesto['oggi'] = timezone.localdate().strftime('%Y%m%d')
        contesto['bacheca_ultimo'] = Annuncio.objects.order_by('-creato_il').first()
    contesto['bacheca_nuovi'] = non_letti_bacheca(request.user, stato)
    contesto['chat_nuovi'] = non_letti_chat(request.user)
    return render(request, 'turni/messaggi.html', contesto)


def elenco_chat(utente):
    """Per la lista stile WhatsApp: ultimo messaggio e non letti di ogni chat."""
    elenco = []
    for c in chat_visibili(utente):
        ultimo = c.messaggi.filter(eliminato=False).select_related('autore', 'autore__dipendente').order_by('-pk').first()
        nuovi = c.messaggi.filter(pk__gt=_letta_fino(utente, c), eliminato=False).exclude(autore=utente).count()
        elenco.append({
            'chat': c,
            'ultimo': ultimo,
            'autore': nome_di(ultimo.autore) if ultimo else '',
            'quando': timezone.localtime(ultimo.creato_il) if ultimo else None,
            'nuovi': nuovi,
        })
    return elenco


@login_required
def chat_nuovi(request):
    """Aggiornamento automatico della chat aperta (ogni pochi secondi)."""
    try:
        dopo = int(request.GET.get('dopo', 0))
        chat = chat_visibili(request.user).get(pk=int(request.GET.get('chat', 0)))
    except (ValueError, Chat.DoesNotExist):
        raise Http404
    responsabile, direzione = e_responsabile(request.user), e_direzione(request.user)
    nuovi = list(chat.messaggi.filter(pk__gt=dopo).select_related('autore', 'autore__dipendente').order_by('pk')[:50])
    if nuovi:
        _segna_letta(request.user, chat, nuovi[-1].pk)
    return JsonResponse({'messaggi': [_messaggio_json(m, request.user, responsabile, direzione) for m in nuovi]})


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
    letture = dict(LetturaChat.objects.filter(utente=utente).values_list('chat_id', 'letta_fino'))
    totale = 0
    for c in chat_visibili(utente):
        totale += c.messaggi.filter(pk__gt=letture.get(c.pk, 0), eliminato=False).exclude(autore=utente).count()
    return totale
