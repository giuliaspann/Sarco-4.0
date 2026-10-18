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


def salva_foto(pulizia, file):
    """Riduce la foto (il telefono la manda già piccola, ma non sempre) e la salva in JPEG."""
    if file.size > MAX_FOTO:
        raise ValueError('foto troppo grande')
    img = ImageOps.exif_transpose(Image.open(file)).convert('RGB')
    img.thumbnail((1600, 1600))
    buf = BytesIO()
    img.save(buf, 'JPEG', quality=75, optimize=True)
    if pulizia.foto:
        pulizia.foto.delete(save=False)
    pulizia.foto.save('foto.jpg', ContentFile(buf.getvalue()), save=False)
