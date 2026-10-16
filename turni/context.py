from django.utils import timezone


def navigazione(request):
    from .models import CambioTurno, RichiestaFerie
    from .richieste import e_responsabile
    from .views import e_capoturno

    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    dip = getattr(user, 'dipendente', None)
    responsabile = e_responsabile(user)
    contesto = {
        'nav_capoturno': e_capoturno(user, timezone.localdate()),
        'nav_dipendente': dip,
        'nav_responsabile': responsabile,
        'nav_ufficio': user.is_staff or responsabile,
    }
    if dip:
        contesto['nav_da_rispondere'] = CambioTurno.objects.filter(
            collega=dip, stato=CambioTurno.Stato.ATTESA_COLLEGA, giorno1__gt=timezone.localdate()
        ).count()
    if responsabile:
        contesto['nav_da_approvare'] = (
            CambioTurno.objects.filter(stato=CambioTurno.Stato.ATTESA_UFFICIO).count()
            + RichiestaFerie.objects.filter(stato=RichiestaFerie.Stato.ATTESA).count()
        )
    return contesto
