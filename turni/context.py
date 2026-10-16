from django.utils import timezone


def navigazione(request):
    from .views import e_capoturno

    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    return {
        'nav_capoturno': e_capoturno(user, timezone.localdate()),
        'nav_dipendente': getattr(user, 'dipendente', None),
    }
