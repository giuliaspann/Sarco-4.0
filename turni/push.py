"""Notifiche sul telefono (Web Push).

Le chiavi VAPID le genera l'app al primo uso e le tiene nel database. L'invio avviene in
un thread separato: chi scrive in chat non aspetta che partano decine di notifiche.
Su iPhone le notifiche arrivano solo se l'app è stata aggiunta alla schermata Home.
"""

import base64
import json
import logging
import os
import threading

from django.conf import settings
from django.db import close_old_connections

log = logging.getLogger(__name__)


def chiavi():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    from .models import ChiaviPush

    c = ChiaviPush.objects.first()
    if c is None:
        privata = ec.generate_private_key(ec.SECP256R1())
        pem = privata.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        punto = privata.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        c = ChiaviPush.objects.create(privata_pem=pem, pubblica=base64.urlsafe_b64encode(punto).rstrip(b'=').decode())
    return c


def _mittente():
    dominio = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
    return f'https://{dominio}' if dominio else 'mailto:noreply@example.com'


def _invia_ora(utenti_ids, titolo, testo, url):
    from py_vapid import Vapid
    from pywebpush import WebPushException, webpush

    from .models import IscrizionePush

    try:
        vapid = Vapid.from_pem(chiavi().privata_pem.encode())
        dati = json.dumps({'titolo': titolo, 'testo': testo[:180], 'url': url})
        for s in IscrizionePush.objects.filter(utente_id__in=utenti_ids):
            try:
                webpush(
                    {'endpoint': s.endpoint, 'keys': {'p256dh': s.p256dh, 'auth': s.auth}},
                    dati,
                    vapid_private_key=vapid,
                    vapid_claims={'sub': _mittente()},
                    ttl=60 * 60 * 12,
                    timeout=10,
                )
            except WebPushException as e:
                stato = getattr(e.response, 'status_code', None)
                if stato in (404, 410):  # il telefono ha revocato le notifiche
                    s.delete()
                else:
                    log.warning('Notifica non inviata (%s): %s', stato, e)
            except Exception:
                log.exception('Errore invio notifica')
    finally:
        close_old_connections()


def invia(utenti_ids, titolo, testo, url='/turni/'):
    utenti_ids = list(utenti_ids)
    if not utenti_ids:
        return
    if getattr(settings, 'PUSH_SINCRONO', False):
        _invia_ora(utenti_ids, titolo, testo, url)
    else:
        threading.Thread(target=_invia_ora, args=(utenti_ids, titolo, testo, url), daemon=True).start()
