"""Credenziali dei dipendenti: PIN generato dall'app e invio all'ufficio turni.

Il PIN è di 8 cifre casuali (generatore crittografico): non lo sceglie il dipendente, così
non ci sono PIN deboli come 12345678. Nel database resta solo l'impronta (hash) della
password: il PIN in chiaro si vede una volta sola, sulla tessera e nell'email all'ufficio.
"""

import logging
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils.text import slugify

from .sicurezza import azzera

log = logging.getLogger('turni.accessi')

CIFRE_PIN = 8


def _pin_debole(pin):
    """Tutte cifre uguali o in fila (12345678, 87654321): si scartano."""
    if len(set(pin)) <= 2:
        return True
    passi = {int(b) - int(a) for a, b in zip(pin, pin[1:])}
    return passi in ({1}, {-1})


def genera_pin():
    while True:
        pin = f'{secrets.randbelow(10 ** CIFRE_PIN):0{CIFRE_PIN}d}'
        if not _pin_debole(pin):
            return pin


def nome_utente_per(dip):
    parole = [p for p in slugify(dip.nome.replace("'", ' ')).split('-') if len(p) > 1]
    base = '.'.join(parole[:2]) or f'dip{dip.pk}'
    nome, i = base, 2
    User = get_user_model()
    while User.objects.filter(username=nome).exclude(dipendente=dip).exists():
        nome, i = f'{base}{i}', i + 1
    return nome


# Gestione accessi: i ruoli da scegliere (Giulia, 13/11/2026). «Operaio» vale per OdL e Capi Turno
# (il Capo Turno lo decide il file turni); «Ufficio» è uno solo: chi è già direzione o amministrazione lo resta,
# gli altri diventano ufficio (HR / ufficio turni).
RUOLI_ACCESSO = [('RI', 'Responsabile Impianto'), ('RP', 'Responsabile Piazzale'), ('OPERAIO', 'Operaio (OdL e Capo Turno)'),
                 ('MAN', 'Manutentore'), ('UFFICIO', 'Ufficio')]
UFFICI = [('RESP_TURNI', 'HR / ufficio turni'), ('DIREZIONE', 'Direzione'), ('AMMINIS', 'Amministrazione')]


def ruolo_accesso(dip):
    """Il ruolo come lo vede l'ufficio in Gestione accessi."""
    if dip.ruolo_app in dict(UFFICI):
        return 'Ufficio'
    if dip.resp_impianto:
        return 'Responsabile Impianto'
    if dip.resp_piazzale:
        return 'Responsabile Piazzale'
    if 'MANUTENTORE' in dip.mansioni:
        return 'Manutentore'
    return 'Operaio'


def imposta_ruolo(dip, ruolo, ufficio=''):
    """Applica il ruolo scelto in Gestione accessi."""
    mansioni = [m for m in dip.mansioni if m != 'MANUTENTORE']
    dip.resp_impianto = ruolo == 'RI'
    dip.resp_piazzale = ruolo == 'RP'
    if ruolo == 'MAN':
        mansioni.append('MANUTENTORE')
    if ruolo == 'UFFICIO':
        dip.ruolo_app = dip.ruolo_app if dip.ruolo_app in dict(UFFICI) else 'RESP_TURNI'
        mansioni = [m for m in mansioni if m != 'OPERAIO'] + (['UFFICIO'] if 'UFFICIO' not in mansioni else [])
    else:
        dip.ruolo_app = 'OPERAIO'
    dip.mansione = ','.join(dict.fromkeys(mansioni)) or 'OPERAIO'
    dip.save(update_fields=['resp_impianto', 'resp_piazzale', 'ruolo_app', 'mansione'])


def crea_credenziali(dip):
    """Crea l'utente se manca e gli assegna un PIN nuovo. Restituisce (nome utente, PIN)."""
    pin = genera_pin()
    utente = dip.utente
    if utente is None:
        utente = get_user_model().objects.create_user(nome_utente_per(dip), first_name=dip.nome_breve)
        dip.utente = utente
        dip.save(update_fields=['utente'])
    utente.set_password(pin)  # cambia anche l'impronta di sessione: il vecchio PIN smette di valere ovunque
    utente.is_active = True
    if not utente.is_superuser:
        utente.is_staff = dip.ruolo_app == 'RESP_TURNI'  # pagine dell'ufficio HR solo per HR / ufficio turni
    utente.save()
    if dip.ruolo_app == 'RESP_TURNI':
        from django.contrib.auth.models import Permission

        utente.user_permissions.add(Permission.objects.get(codename='approva_richieste', content_type__app_label='turni'))
    azzera(utente.username)
    return utente.username, pin


def email_configurata():
    return bool(getattr(settings, 'UFFICIO_TURNI_EMAIL', '')) and (
        bool(getattr(settings, 'RESEND_API_KEY', '')) or bool(getattr(settings, 'EMAIL_HOST', ''))
    )


def testo_email(credenziali, indirizzo_app):
    righe = [
        "Credenziali per l'app Sarco 4.0.",
        "Consegna a ciascuno solo le sue e cancella questa email dopo la consegna.",
        '',
        f'App: {indirizzo_app}',
        '',
    ]
    for c in credenziali:
        righe.append(f"{c['nome']}  —  nome utente: {c['username']}  —  PIN: {c['pin']}")
    righe += [
        '',
        'Il PIN lo genera l\'app ed è valido finché non se ne crea uno nuovo da Ufficio > Dipendenti.',
    ]
    return '\n'.join(righe)


def invia_all_ufficio(credenziali, indirizzo_app):
    """Manda le credenziali all'indirizzo dell'ufficio turni. Ritorna True se l'email è partita.

    Su Railway (piano Trial/Hobby) le porte SMTP sono chiuse: si usa Resend via HTTPS
    se c'è RESEND_API_KEY, altrimenti il server SMTP indicato in EMAIL_HOST.
    """
    if not credenziali or not email_configurata():
        return False
    oggetto = (
        f"Sarco 4.0: credenziali di {credenziali[0]['nome']}"
        if len(credenziali) == 1
        else f'Sarco 4.0: credenziali di {len(credenziali)} dipendenti'
    )
    corpo = testo_email(credenziali, indirizzo_app)
    try:
        if getattr(settings, 'RESEND_API_KEY', ''):
            import requests

            r = requests.post(
                'https://api.resend.com/emails',
                headers={'Authorization': f'Bearer {settings.RESEND_API_KEY}'},
                json={
                    'from': settings.DEFAULT_FROM_EMAIL,
                    'to': [settings.UFFICIO_TURNI_EMAIL],
                    'subject': oggetto,
                    'text': corpo,
                },
                timeout=15,
            )
            r.raise_for_status()
        else:
            send_mail(oggetto, corpo, settings.DEFAULT_FROM_EMAIL, [settings.UFFICIO_TURNI_EMAIL])
        return True
    except Exception:
        log.exception("Invio delle credenziali all'ufficio turni non riuscito")
        return False


def qr_svg(testo):
    """QR code come immagine SVG (data URI), da stampare sulla tessera."""
    import segno

    return segno.make(testo, error='m').svg_data_uri(scale=4, border=2, dark='#00384f')
