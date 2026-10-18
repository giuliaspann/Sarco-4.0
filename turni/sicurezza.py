"""Difese comuni: blocco dei tentativi di accesso, controllo delle notifiche e intestazioni di sicurezza."""

import logging
from datetime import timedelta
from urllib.parse import urlparse

from django import forms
from django.utils import timezone

log = logging.getLogger('turni.sicurezza')

# Per nome utente: 5 errori -> 15 minuti di blocco. Per indirizzo di rete: 20 errori -> 30 minuti.
LIMITI = {'u': (5, timedelta(minutes=15)), 'ip': (20, timedelta(minutes=30))}
# Dopo questo tempo senza errori il conteggio riparte da zero
FINESTRA = timedelta(minutes=15)

MESSAGGIO_BLOCCO = 'Troppi tentativi sbagliati: riprova tra qualche minuto o chiedi in ufficio.'


def ip_client(request):
    """Railway aggiunge l'indirizzo vero del client in fondo a X-Forwarded-For."""
    inoltrato = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if inoltrato:
        return inoltrato.split(',')[-1].strip()
    return request.META.get('REMOTE_ADDR', '')


def _chiavi(request, username):
    chiavi = [('u', f'u:{(username or "").strip().lower()[:150]}')]
    if request is not None:
        chiavi.append(('ip', f'ip:{ip_client(request)}'))
    return chiavi


def bloccato(request, username):
    from .models import BloccoAccesso

    chiavi = [c for _, c in _chiavi(request, username)]
    return BloccoAccesso.objects.filter(chiave__in=chiavi, bloccato_fino__gt=timezone.now()).exists()


def registra_errore(request, username):
    from .models import BloccoAccesso

    adesso = timezone.now()
    for tipo, chiave in _chiavi(request, username):
        massimo, durata = LIMITI[tipo]
        b, nuovo = BloccoAccesso.objects.get_or_create(chiave=chiave)
        attivo = b.bloccato_fino and b.bloccato_fino > adesso
        if not nuovo and not attivo and adesso - b.aggiornato_il > FINESTRA:
            b.tentativi = 0
        b.tentativi += 1
        if b.tentativi >= massimo:
            b.bloccato_fino = adesso + durata
            b.tentativi = 0
            log.warning('Accesso bloccato per %s fino a %s', chiave, b.bloccato_fino)
        b.save()


def azzera(username):
    from .models import BloccoAccesso

    BloccoAccesso.objects.filter(chiave=f'u:{(username or "").strip().lower()}').delete()


class ProtezioneAccesso:
    """Da mettere davanti a un AuthenticationForm (login dell'app e del pannello admin)."""

    def clean(self):
        username = (self.cleaned_data.get('username') or '').strip().lower()
        self.cleaned_data['username'] = username
        if bloccato(self.request, username):
            raise forms.ValidationError(MESSAGGIO_BLOCCO, code='bloccato')
        try:
            pulito = super().clean()
        except forms.ValidationError:
            registra_errore(self.request, username)
            raise
        azzera(username)
        return pulito


# Servizi di notifica dei browser: le notifiche partono solo verso questi indirizzi
SERVIZI_PUSH = (
    'fcm.googleapis.com', 'android.googleapis.com', 'updates.push.services.mozilla.com',
    'push.services.mozilla.com', 'web.push.apple.com', 'notify.windows.com',
)


def endpoint_push_valido(url):
    try:
        u = urlparse(str(url))
    except ValueError:
        return False
    host = (u.hostname or '').lower()
    return u.scheme == 'https' and any(host == s or host.endswith('.' + s) for s in SERVIZI_PUSH)


CSP = '; '.join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob:",
    "connect-src 'self'",
    "worker-src 'self'",
    "manifest-src 'self'",
    "frame-ancestors 'none'",
    "form-action 'self'",
    "base-uri 'self'",
    "object-src 'none'",
])
# il pannello admin di Django usa script e stili inline
CSP_ADMIN = CSP.replace("script-src 'self'", "script-src 'self' 'unsafe-inline'").replace(
    "style-src 'self'", "style-src 'self' 'unsafe-inline'"
)


class IntestazioniSicurezza:
    """Content-Security-Policy e Permissions-Policy su tutte le risposte."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        risposta = self.get_response(request)
        risposta.setdefault('Content-Security-Policy', CSP_ADMIN if request.path.startswith('/admin/') else CSP)
        risposta.setdefault('Permissions-Policy', 'camera=(self), microphone=(), geolocation=(), payment=()')
        return risposta
