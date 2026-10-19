from datetime import timedelta
from io import BytesIO

from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageOps

from .models import ElementoPulizia, Fascia, Pulizia, RegolaPulizia, Turno

# Fino a quest'ora del mattino il turno "attuale" di chi ha fatto la notte è quello di ieri
FINE_NOTTE = 10


def genera_pulizie(turno):
    """Crea le voci di pulizia previste dalle regole per il turno (una volta sola per elemento)."""
    if not turno.lavora:
        return
    regole = RegolaPulizia.objects.filter(elemento__attivo=True).select_related('elemento')
    for regola in regole:
        if regola.si_applica(turno):
            Pulizia.objects.get_or_create(turno=turno, elemento=regola.elemento)


def turno_attuale(dipendente):
    adesso = timezone.localtime()
    oggi = adesso.date()
    if adesso.hour < FINE_NOTTE:
        ieri = Turno.objects.filter(dipendente=dipendente, data=oggi - timedelta(days=1), fascia=Fascia.NOTTE).first()
        if ieri:
            return ieri
    return Turno.objects.filter(dipendente=dipendente, data=oggi).first()


def mezzi_aggiungibili(turno):
    gia = turno.pulizie.values_list('elemento_id', flat=True)
    return ElementoPulizia.objects.filter(attivo=True, tipo=ElementoPulizia.Tipo.MEZZO).exclude(pk__in=gia)


MAX_FOTO = 15 * 1024 * 1024
# immagini enormi (decine di migliaia di pixel per lato) vengono rifiutate
Image.MAX_IMAGE_PIXELS = 50_000_000


def salva_foto(pulizia, file, campo='foto'):
    """Riduce la foto (il telefono la manda già piccola, ma non sempre) e la salva in JPEG."""
    if file.size > MAX_FOTO:
        raise ValueError('foto troppo grande')
    img = ImageOps.exif_transpose(Image.open(file)).convert('RGB')
    img.thumbnail((1600, 1600))
    buf = BytesIO()
    img.save(buf, 'JPEG', quality=75, optimize=True)
    f = getattr(pulizia, campo)
    if f:
        f.delete(save=False)
    f.save('foto.jpg', ContentFile(buf.getvalue()), save=False)


def aggiungibili(turno):
    """Per "Segnala pulizia aggiuntiva": mezzi e zone non già nella lista del turno."""
    gia = turno.pulizie.values_list('elemento_id', flat=True)
    return ElementoPulizia.objects.filter(attivo=True).exclude(pk__in=gia).order_by('tipo', 'nome')


def in_turno_oggi(escluso=None):
    """A chi si può chiedere una pulizia: chi lavora oggi (o fa la notte iniziata ieri)."""
    oggi = timezone.localdate()
    adesso = timezone.localtime()
    turni = Turno.objects.filter(data=oggi, settimana__pubblicata=True, dipendente__attivo=True)
    if adesso.hour < FINE_NOTTE:
        turni = turni | Turno.objects.filter(data=oggi - timedelta(days=1), fascia=Fascia.NOTTE, settimana__pubblicata=True,
                                             dipendente__attivo=True)
    turni = [t for t in turni.select_related('dipendente') if t.lavora and t.dipendente_id != getattr(escluso, 'pk', None)]
    return sorted(turni, key=lambda t: t.dipendente.nome)


def richiedi_pulizia(utente, turno, elemento, nota=''):
    from . import push

    if turno.pulizie.filter(elemento=elemento).exists():
        raise ValueError(f'{elemento.nome} è già nella lista di {turno.dipendente.nome_breve}.')
    p = Pulizia.objects.create(turno=turno, elemento=elemento, richiesta_da=utente, nota=nota[:300])
    if turno.dipendente.utente_id:
        da = getattr(getattr(utente, 'dipendente', None), 'nome_breve', None) or utente.get_username()
        push.invia([turno.dipendente.utente_id], '🧹 Ti chiedono una pulizia', f'{elemento.nome} (da {da})', f'/turni/pulizie/{turno.pk}/')
    return p
