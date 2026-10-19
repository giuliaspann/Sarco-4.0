"""La chat dell'assistente digitale (il fumetto in basso a destra, come sui siti)."""

import json

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_POST

from . import assistente
from .models import ConversazioneAssistente


def _conversazione(utente, nuova=False):
    c = ConversazioneAssistente.objects.filter(utente=utente).first()
    if nuova or c is None or len(c.messaggi) > assistente.MAX_MESSAGGI:
        c = ConversazioneAssistente.objects.create(utente=utente)
    return c


def _serve(request):
    if not assistente.attivo():
        raise Http404


def _dati(request):
    try:
        return json.loads(request.body or b'{}')
    except ValueError:
        return {}


@login_required
def chat(request):
    _serve(request)
    if request.method == 'POST':
        testo = (_dati(request).get('testo') or '').strip()
        if not testo:
            return JsonResponse({'errore': 'Scrivi un messaggio.'}, status=400)
        c = _conversazione(request.user)
        try:
            risposta, proposte = assistente.rispondi(c, testo, request.user)
        except assistente.Errore as e:
            return JsonResponse({'errore': str(e)}, status=502)
        return JsonResponse({'risposta': risposta, 'proposte': [{'id': p['id'], 'riassunto': p['riassunto']} for p in proposte]})
    c = ConversazioneAssistente.objects.filter(utente=request.user).first()
    return JsonResponse({
        'messaggi': c.per_lo_schermo() if c else [],
        'proposte': [{'id': p['id'], 'riassunto': p['riassunto']} for p in c.proposte] if c else [],
        'suggerimenti': assistente.suggerimenti(request.user),
    })


@login_required
@require_POST
def conferma(request):
    _serve(request)
    d = _dati(request)
    c = ConversazioneAssistente.objects.filter(utente=request.user).first()
    if not c:
        return JsonResponse({'errore': 'Nessuna conversazione.'}, status=400)
    try:
        esito = assistente.conferma(c, str(d.get('id')), bool(d.get('accetta')), request.user)
    except assistente.Errore as e:
        return JsonResponse({'errore': str(e)}, status=400)
    return JsonResponse({'esito': esito})


@login_required
@require_POST
def nuova(request):
    _serve(request)
    _conversazione(request.user, nuova=True)
    return JsonResponse({'suggerimenti': assistente.suggerimenti(request.user)})
