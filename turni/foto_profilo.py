"""Il tondino con la foto, uguale per tutti gli utenti: dipendenti e ufficio (Giulia, 11/11/2026)."""

from django.urls import reverse


def foto_url(utente):
    """L'indirizzo della foto profilo, o '' se non c'è."""
    if utente is None:
        return ''
    dip = getattr(utente, 'dipendente', None)
    if dip and dip.foto:
        return reverse('turni:foto_profilo_img', args=[dip.pk]) + f'?v={dip.foto.name[-12:]}'
    try:
        f = utente.foto_profilo
    except Exception:  # nessuna foto
        return ''
    if f.foto:
        return reverse('turni:foto_utente_img', args=[utente.pk]) + f'?v={f.foto.name[-12:]}'
    return ''
