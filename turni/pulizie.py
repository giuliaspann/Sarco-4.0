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
    # le voci "promemoria" (es. controllo vagli zig-zag) non si creano da sole: le regole dicono solo chi vede l'avviso,
    # il controllo lo assegna il Capo Turno a una persona
    regole = RegolaPulizia.objects.filter(elemento__attivo=True, elemento__promemoria=False).select_related('elemento')
    for regola in regole:
        if regola.si_applica(turno):
            Pulizia.objects.get_or_create(turno=turno, elemento=regola.elemento)


def promemoria_di(turno):
    """Gli avvisi del turno (es. «13:00 fermo produzione · controllo vagli zig-zag») per chi lavora lì,
    con il controllo, se il Capo Turno l'ha già assegnato a qualcuno."""
    if not turno or not turno.lavora:
        return []
    avvisi = []
    for regola in RegolaPulizia.objects.filter(elemento__attivo=True, elemento__promemoria=True).select_related('elemento'):
        if regola.si_applica(turno) and regola.elemento not in [a['elemento'] for a in avvisi]:
            e = regola.elemento
            controllo = Pulizia.objects.filter(elemento=e, turno__data=turno.data, turno__fascia=turno.fascia).select_related(
                'turno__dipendente').first()
            if controllo is None:
                controllo = _al_manutentore(e, turno)
            avvisi.append({
                'elemento': e,
                'ora': timezone.localtime(turno.fine - timedelta(minutes=e.minuti_prima_fine or 0)),
                'controllo': controllo,
            })
    # chi ha il controllo senza lavorare all'impianto (es. il manutentore) vede comunque l'avviso
    for p in turno.pulizie.filter(elemento__promemoria=True).select_related('elemento', 'turno__dipendente'):
        if p.elemento not in [a['elemento'] for a in avvisi]:
            avvisi.append({'elemento': p.elemento, 'ora': timezone.localtime(p.da_quando), 'controllo': p})
    return avvisi


def manutentore_del_turno(turno):
    from .models import Mansione, Postazione

    for t in Turno.objects.filter(data=turno.data, fascia=turno.fascia, dipendente__attivo=True).select_related('dipendente'):
        if (t.postazione == Postazione.MANUT or any(r.upper() == 'MAN' for _, r in t.lista_incarichi)
                or Mansione.MANUTENTORE in t.dipendente.mansioni):
            return t
    return None


def _al_manutentore(elemento, turno):
    """Il controllo (es. vagli zig-zag) va al manutentore di turno; se non c'è, lo assegna il Capo Turno."""
    from . import push

    t = manutentore_del_turno(turno)
    if t is None:
        return None
    p, nuova = Pulizia.objects.get_or_create(turno=t, elemento=elemento)
    if nuova and t.dipendente.utente_id:
        push.invia([t.dipendente.utente_id], f'⏸️ {elemento.nome}',
                   f'Alle {timezone.localtime(p.da_quando):%H:%M} fermo produzione: il controllo è tuo.', f'/turni/pulizie/{t.pk}/')
    return p



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
        push.invia([turno.dipendente.utente_id], '🧹 Ti chiedono una pulizia', f'{p.titolo} (da {da})', f'/turni/pulizie/{turno.pk}/',
                   mittente=utente, tipo='pulizia', oggetto_id=p.pk)
    return p


LUOGHI_PULIZIA = ['IMP1', 'IMP2', 'PIAZZALE', 'METALLI', 'SABBIA', 'MEZZI', 'ANALISI']

# "Richiedi pulizia": per ogni area, le postazioni di chi ci lavora (li mostro per primi)
POSTAZIONI_AREA = {
    'IMP1': ['IMP1', 'PALISTA', 'MULINO'], 'IMP2': ['IMP2', 'BARROTTI'], 'PIAZZALE': ['PIAZZALE', 'PALISTA'],
    'METALLI': ['METALLI'], 'SABBIA': ['SABBIA'], 'MEZZI': ['PALISTA', 'AUTISTA'], 'ANALISI': ['ANALISI'],
}


def puo_richiedere(utente):
    """Le pulizie le chiedono il responsabile impianto, il responsabile piazzale, l'ufficio
    e il Capo Turno in servizio ("Pulizia richiesta", Giulia 10/11)."""
    from .views import e_capoturno

    dip = getattr(utente, 'dipendente', None)
    return (utente.is_staff or bool(dip and (dip.resp_impianto or dip.resp_piazzale))
            or e_capoturno(utente, timezone.localdate()))


def in_turno(giorno, fascia, area):
    """Chi lavora quel giorno in quel turno: prima chi è nell'area, poi gli altri."""
    fasce = [Fascia.MATTINA, Fascia.ALTRO] if fascia == Fascia.MATTINA else [fascia]
    turni = [t for t in Turno.objects.filter(data=giorno, fascia__in=fasce, settimana__pubblicata=True, dipendente__attivo=True)
             .select_related('dipendente').order_by('dipendente__nome') if t.lavora]
    vicini = POSTAZIONI_AREA.get(area, [])
    return [t for t in turni if t.postazione in vicini], [t for t in turni if t.postazione not in vicini]


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


# ---------------------------------------------------------------- Capo Turno e responsabile piazzale

ORA_NOTTE = 17  # entro quest'ora il responsabile piazzale assegna le pulizie della notte ai Capi Turno


def e_resp_piazzale(utente):
    return utente.is_staff or bool(getattr(getattr(utente, 'dipendente', None), 'resp_piazzale', False))


def resp_piazzale():
    from django.contrib.auth import get_user_model

    return list(get_user_model().objects.filter(is_active=True, dipendente__resp_piazzale=True).values_list('pk', flat=True))


def squadra(turno):
    """Chi lavora nello stesso turno del Capo Turno: prima la sua postazione, poi le altre."""
    fascia = Fascia.MATTINA if turno.fascia == Fascia.ALTRO else turno.fascia
    fasce = [Fascia.MATTINA, Fascia.ALTRO] if fascia == Fascia.MATTINA else [fascia]
    altri = Turno.objects.filter(data=turno.data, fascia__in=fasce, settimana__pubblicata=True, dipendente__attivo=True
                                 ).exclude(pk=turno.pk).select_related('dipendente')
    return sorted(altri, key=lambda t: (t.postazione != turno.postazione, t.postazione == '', t.postazione, t.dipendente.nome))


def capi_della_notte(giorno=None):
    giorno = giorno or timezone.localdate()
    return list(Turno.objects.filter(data=giorno, fascia=Fascia.NOTTE, capoturno=True, settimana__pubblicata=True)
                .select_related('dipendente').order_by('postazione', 'dipendente__nome'))


def passa_pulizia(utente, p, turno):
    """Il Capo Turno della notte passa a un operatore una pulizia ricevuta dal responsabile piazzale."""
    from . import push

    if p.elemento_id and turno.pulizie.filter(elemento=p.elemento).exists():
        raise ValueError(f'{p.titolo} è già nella lista di {turno.dipendente.nome_breve}.')
    da = p.richiesta_da.dipendente.nome_breve if p.richiesta_da_id and hasattr(p.richiesta_da, 'dipendente') else ''
    if da and 'da ' + da not in p.nota:
        p.nota = (f'{p.nota} (da {da})' if p.nota else f'Da {da}')[:300]
    p.turno, p.richiesta_da = turno, utente
    p.save()
    if turno.dipendente.utente_id:
        push.invia([turno.dipendente.utente_id], '🧹 Ti chiedono una pulizia', f'{p.titolo} (dal Capo Turno)', f'/turni/pulizie/{turno.pk}/',
                   mittente=utente, tipo='pulizia', oggetto_id=p.pk)


def pulizia_generale_in_attesa():
    """La decisione sulla pulizia generale dell'Impianto 2, se è il momento (ogni 2 settimane). Avvisa il responsabile."""
    from . import push
    from .models import PuliziaGenerale

    ultima = PuliziaGenerale.objects.first()
    if ultima and not ultima.esito:
        return ultima
    oggi = timezone.localdate()
    if ultima and ultima.data > oggi - timedelta(days=PuliziaGenerale.OGNI_GIORNI):
        return None
    nuova = PuliziaGenerale.objects.create(data=oggi)
    push.invia(resp_piazzale(), '🧹 Pulizia generale Impianto 2', 'È da fare? Rispondi «sì» e assegnala, oppure «non necessaria».',
               '/turni/pulizie/piazzale/')
    return nuova


def da_convalidare_piazzale():
    """Quelle che convalida solo lui e quelle che hanno già l'ok del Capo Turno."""
    from django.db.models import Q

    C = ElementoPulizia.Convalida
    return Pulizia.objects.filter(
        Q(elemento__convalida=C.PIAZZALE) | Q(elemento__convalida=C.CT_RP, ok_capoturno_il__isnull=False),
        stato=Pulizia.Stato.FATTA, turno__data__gte=timezone.localdate() - timedelta(days=3),
    ).select_related('turno__dipendente', 'elemento', 'ok_capoturno_da__dipendente')
