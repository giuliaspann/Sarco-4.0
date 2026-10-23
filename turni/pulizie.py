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
    from .views import ORDINE_GRUPPI

    posto = {p: i for i, p in enumerate(ORDINE_GRUPPI)}
    ore = {Fascia.MATTINA: 0, Fascia.ALTRO: 0, Fascia.GIORNALIERO: 1, Fascia.POMERIGGIO: 2, Fascia.NOTTE: 3}
    return sorted(turni, key=lambda t: (t.postazione == '', posto.get(t.postazione, 99), ore.get(t.fascia, 9),
                                        not t.capoturno, t.dipendente.nome))


def richiedi_pulizia(utente, turno, elemento, nota=''):
    from . import push

    # senza elemento: "Richiedi pulizia" della nuova app, dove e cosa sono scritti nel commento
    if elemento and turno.pulizie.filter(elemento=elemento).exists():
        raise ValueError(f'{elemento.nome} è già nella lista di {turno.dipendente.nome_breve}.')
    if not elemento and not nota.strip():
        raise ValueError('Scrivi dove e cosa va pulito.')
    p = Pulizia.objects.create(turno=turno, elemento=elemento, richiesta_da=utente, nota=nota[:300])
    if turno.dipendente.utente_id:
        da = getattr(getattr(utente, 'dipendente', None), 'nome_breve', None) or utente.get_username()
        push.invia([turno.dipendente.utente_id], '🧹 Ti chiedono una pulizia', f'{p.titolo} (da {da})', f'/turni/pulizie/{turno.pk}/')
    return p


LUOGHI_PULIZIA = ['IMP1', 'IMP2', 'PIAZZALE', 'METALLI', 'SABBIA', 'MEZZI', 'ANALISI']


def scelte_pulizia(escludi=()):
    """Per "Cosa hai pulito / cosa è da pulire": prima il luogo (come in Manutenzione), poi la cosa.
    Le cose sono le voci di pulizia e le macchine e i mezzi dell'elenco della manutenzione."""
    from .models import Luogo, Macchina
    from .views_manutenzione import ICONE_LUOGHI

    voci = {v: [] for v in LUOGHI_PULIZIA}
    nomi = set()
    for e in ElementoPulizia.objects.filter(attivo=True).exclude(pk__in=list(escludi)).order_by('nome'):
        luogo = e.luogo if e.luogo in voci else ('MEZZI' if e.tipo == ElementoPulizia.Tipo.MEZZO else '')
        nomi.add(e.nome.lower())
        voci.setdefault(luogo, []).append((f'e{e.pk}', e.nome, '🚜' if e.tipo == ElementoPulizia.Tipo.MEZZO else '🧹'))
    gia = {n.lower() for n in ElementoPulizia.objects.filter(pk__in=list(escludi)).values_list('nome', flat=True)}
    for m in Macchina.objects.filter(attiva=True, luogo__in=LUOGHI_PULIZIA).exclude(tipo=Macchina.Tipo.SEGNALETICA).order_by('nome'):
        if m.nome.lower() not in nomi and m.nome.lower() not in gia:
            voci[m.luogo].append((f'm{m.pk}', m.nome, '🚜' if m.tipo == Macchina.Tipo.MEZZO else '⚙️'))
    luoghi = [(v, Luogo(v).label, ICONE_LUOGHI.get(v, '📍'), voci[v]) for v in LUOGHI_PULIZIA if voci[v]]
    if voci.get(''):
        luoghi.append(('ALTRO', 'Altro', '📍', voci['']))
    return luoghi


def elemento_da_scelta(valore):
    """'e12' = voce di pulizia; 'm34' = macchina della manutenzione (diventa una voce di pulizia la prima volta)."""
    from .models import Macchina

    valore = valore or ''
    if valore.startswith('e') and valore[1:].isdigit():
        return ElementoPulizia.objects.filter(pk=valore[1:], attivo=True).first()
    if valore.startswith('m') and valore[1:].isdigit():
        m = Macchina.objects.filter(pk=valore[1:], attiva=True).first()
        if m:
            e, _ = ElementoPulizia.objects.get_or_create(nome=m.nome[:100], defaults={
                'tipo': ElementoPulizia.Tipo.MEZZO if m.tipo == Macchina.Tipo.MEZZO else ElementoPulizia.Tipo.ZONA,
                'luogo': m.luogo})
            return e if e.attivo else None
    if valore.isdigit():
        return ElementoPulizia.objects.filter(pk=valore, attivo=True).first()
    return None
