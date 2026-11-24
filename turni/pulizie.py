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
    if turno.capoturno:
        return  # i Capi Turno non fanno le pulizie: supervisionano, fanno le foto e confermano (regola generale, 11/11/2026)
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


# tutte le aree di lavoro, nell'ordine di Luogo (Giulia, 24/11/2026)
LUOGHI_PULIZIA = ['IMP1', 'IMP2', 'METALLI', 'ROTOVAGLIO', 'GRANELLA', 'SABBIA', 'PIAZZALE', 'OFFICINA', 'MAGAZZINO', 'ANALISI',
                  'MEZZI', 'ESTERNI']

# "Richiedi pulizia": per ogni area, le postazioni di chi ci lavora (li mostro per primi)
# (la postazione SABBIA del file turni è la Granella, SUPERBI è la Sabbia)
POSTAZIONI_AREA = {
    'IMP1': ['IMP1', 'PALISTA'], 'IMP2': ['IMP2', 'BARROTTI'], 'METALLI': ['METALLI'], 'ROTOVAGLIO': ['ROTOVAGLIO'],
    'GRANELLA': ['SABBIA', 'MULINO'], 'SABBIA': ['SUPERBI'], 'PIAZZALE': ['PIAZZALE', 'PALISTA'], 'OFFICINA': ['MANUT'],
    'MAGAZZINO': ['MAGAZZINO'], 'ANALISI': ['ANALISI'], 'MEZZI': ['PALISTA', 'MANUT'], 'ESTERNI': ['AUTISTA'],
}


def puo_richiedere(utente):
    """Tutti possono chiedere una pulizia (Giulia, 13/11/2026): il RP la assegna, gli altri la mandano al RP.
    Anche chi non ha la scheda dipendente: «tutti devono vedere tutto» (Giulia, 24/11/2026)."""
    return utente.is_authenticated


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
    # tutte le aree, anche quelle senza voci: in fondo a ognuna «Pulizia generica» (Giulia, 24/11/2026)
    for v in LUOGHI_PULIZIA:
        voci[v].append((f'g{v}', f'Pulizia generica {Luogo(v).label}', '🧹'))
    luoghi = [(v, Luogo(v).label, ICONE_LUOGHI.get(v, '📍'), voci[v]) for v in LUOGHI_PULIZIA]
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
    if valore.startswith('g') and valore[1:] in LUOGHI_PULIZIA:
        from .models import Luogo

        e, _ = ElementoPulizia.objects.get_or_create(nome=f'Pulizia generica {Luogo(valore[1:]).label}'[:100], defaults={
            'tipo': ElementoPulizia.Tipo.ZONA, 'luogo': valore[1:]})
        return e if e.attivo else None
    if valore.isdigit():
        return ElementoPulizia.objects.filter(pk=valore, attivo=True).first()
    return None


# ---------------------------------------------------------------- Capo Turno e responsabile piazzale

ORA_NOTTE = 17  # entro quest'ora il responsabile piazzale assegna le pulizie della notte ai Capi Turno


def e_resp_piazzale(utente):
    """Convalida le pulizie solo il responsabile piazzale, non l'ufficio (Giulia, 13/11/2026)."""
    return bool(getattr(getattr(utente, 'dipendente', None), 'resp_piazzale', False))


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
    """La decisione sulla pulizia generale dell'Impianto 2, se è il momento (ogni 2 settimane). Avvisa il responsabile.
    Spenta dal 21/11/2026: la pulizia generale Impianto 2 non è più nel file delle regole."""
    return None
    from . import push  # noqa: E402 (resta il codice di prima, se la si vuole riaccendere)
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
    """Quelle che convalida solo lui, quelle che hanno già l'ok del Capo Turno e le straordinarie fatte dal Capo Turno."""
    from .piano_pulizie import Q_AL_RP

    return Pulizia.objects.filter(
        Q_AL_RP, stato=Pulizia.Stato.FATTA, turno__data__gte=timezone.localdate() - timedelta(days=3),
    ).select_related('turno__dipendente', 'elemento', 'ok_capoturno_da__dipendente')



# ---------------------------------------------------------------- richieste al responsabile piazzale (Giulia, 13/11/2026)
# Tutti possono chiedere una pulizia o una straordinaria; assegna direttamente solo il RP. Le altre richieste
# (operai, Capi Turno, responsabile impianto, ufficio) arrivano al RP, che le approva e sceglie a chi darle.

def chiedi_al_rp(utente, tipo, luogo, giorno, fascia, testo, foto=None):
    from . import manutenzione as mn
    from .models import Luogo, Straordinaria

    s = Straordinaria(tipo=tipo, luogo=luogo, giorno=giorno, turno=fascia, testo=(testo or '')[:1000], chiesta_da=utente)
    if foto:
        salva_foto(s, foto)
    s.save()
    nome = Luogo(luogo).label if luogo in Luogo.values else luogo
    mn.avvisa(resp_piazzale(), utente, f'🧹 {s.get_tipo_display()} · {nome}',
              f'{giorno:%a %d/%m} {fascia}: {testo}'[:300], f'/turni/pulizie/richieste/{s.pk}/', tipo='straordinaria', oggetto_id=s.pk)
    return s


def approva_richiesta(utente, s, turno):
    """Il RP approva e assegna: diventa una pulizia della persona scelta (con la foto della richiesta)."""
    from django.core.files.base import ContentFile

    from . import manutenzione as mn
    from .models import Luogo, Straordinaria

    nome = Luogo(s.luogo).label if s.luogo in Luogo.values else s.luogo
    da = getattr(getattr(s.chiesta_da, 'dipendente', None), 'nome_breve', '') or (s.chiesta_da.get_username() if s.chiesta_da else '')
    p = Pulizia(turno=turno, elemento=None, richiesta_da=utente, nota=f'{nome}: {s.testo} (chiesta da {da})'[:300])
    if s.foto:
        with s.foto.open('rb') as f:
            p.foto_richiesta.save('richiesta.jpg', ContentFile(f.read()), save=False)
    p.save()
    s.stato, s.gestita_da, s.gestita_il = Straordinaria.Stato.INOLTRATA, utente, timezone.now()
    s.save()
    mn.avvisa([turno.dipendente.utente_id], utente, '🧹 Ti assegnano una pulizia', f'{p.titolo}',
              f'/turni/pulizie/{turno.pk}/', tipo='pulizia', oggetto_id=p.pk)
    if s.chiesta_da_id:
        mn.avvisa([s.chiesta_da_id], utente, '✅ Pulizia approvata', f'{nome}: assegnata a {turno.dipendente.nome_breve}',
                  f'/turni/pulizie/voce/{p.pk}/')
    return p


def rifiuta_richiesta(utente, s, nota=''):
    from . import manutenzione as mn
    from .models import Straordinaria

    s.stato, s.gestita_da, s.gestita_il = Straordinaria.Stato.RIFIUTATA, utente, timezone.now()
    s.save()
    if s.chiesta_da_id:
        mn.avvisa([s.chiesta_da_id], utente, '🧹 Pulizia non approvata', (nota or s.testo)[:300], '/turni/pulizie/')



def usa_telefono(turno):
    """Gli operatori di linea dell'Impianto 1 non usano il telefono: le loro conferme le manda il Capo Turno."""
    if not turno or not turno.lavora or turno.capoturno:
        return True
    return not any(p == 'IMP1' and (r or '').upper() == 'ODL' for p, r in turno.lista_incarichi) and not (
        turno.postazione == 'IMP1' and (turno.ruolo or '').upper() == 'ODL')


# ---------------------------------------------------------------- file «Regole Pulizie - unico.xlsx» (Giulia, 21/11/2026)

MAX_VIDEO = 100 * 1024 * 1024
CAMPO_DI = {'PRIMA': 'foto_prima', 'DOPO': 'foto', 'MOTIVO': 'foto'}


def _jpeg(file):
    if file.size > MAX_FOTO:
        raise ValueError('foto troppo grande')
    img = ImageOps.exif_transpose(Image.open(file)).convert('RGB')
    img.thumbnail((1600, 1600))
    buf = BytesIO()
    img.save(buf, 'JPEG', quality=75, optimize=True)
    return ContentFile(buf.getvalue(), name='foto.jpg')


def salva_file(p, files, momento):
    """Più foto e più video per ogni pulizia o controllo. La prima foto va nel campo di sempre (foto prima / foto dopo),
    le altre foto e tutti i video negli allegati. Chi rimanda i file di un momento sostituisce quelli di prima.
    ValueError se un file non si legge o è troppo grande (niente viene salvato a metà per le foto principali)."""
    from .models import AllegatoPulizia

    files = [f for f in files if f]
    if not files:
        return
    if p.pk is None:
        p.save()
    for a in p.allegati.filter(momento=momento):
        a.file.delete(save=False)
        a.delete()
    prima_foto = True
    for f in files:
        tipo = (getattr(f, 'content_type', '') or '').lower()
        if tipo.startswith('video/'):
            if f.size > MAX_VIDEO:
                raise ValueError('video troppo grande (massimo 100 MB)')
            AllegatoPulizia.objects.create(pulizia=p, momento=momento, file=f, video=True, tipo_file=tipo[:60])
        elif prima_foto:
            salva_foto(p, f, CAMPO_DI[momento])
            prima_foto = False
        else:
            AllegatoPulizia.objects.create(pulizia=p, momento=momento, file=_jpeg(f), tipo_file='image/jpeg')


def ha_file(p, momento):
    campo = getattr(p, CAMPO_DI[momento])
    return bool(campo) or (p.pk is not None and p.allegati.filter(momento=momento).exists())


def conferma_il_capo(p):
    """Chi conferma la pulizia (colonna «Chi conferma sull'app»): il Capo Turno per gli OdL dell'Impianto 1, altrimenti chi la fa."""
    return not usa_telefono(p.turno)


def capi_del_turno(p):
    from .piano_pulizie import fasce_di, sigla

    return [t.dipendente.utente_id for t in Turno.objects.filter(
        data=p.turno.data, fascia__in=fasce_di(sigla(p.turno.fascia)), capoturno=True, dipendente__attivo=True)
        .select_related('dipendente') if t.dipendente.utente_id]


def link_effettuata(p):
    from django.urls import reverse

    if conferma_il_capo(p):
        return reverse('turni:pulizia_voce', args=[p.pk])
    return reverse('turni:pulizie_turno', args=[p.turno_id]) + f'?fai=assegnata&voce={p.pk}'


def link_non_effettuata(p):
    from django.urls import reverse

    if conferma_il_capo(p):
        return reverse('turni:pulizia_voce', args=[p.pk]) + '?fai=impedita'
    if p.elemento_id and p.elemento.controllo:
        return link_effettuata(p)  # nei controlli «Non effettuata» = «Segnala un problema», nello stesso modulo
    return reverse('turni:pulizie_turno', args=[p.turno_id]) + f'?fai=impedimento&voce={p.pk}'


def puo_rispondere_avviso(utente, p):
    """I 3 tasti dell'avviso li usa solo chi conferma la pulizia."""
    if p.stato not in (Pulizia.Stato.DA_FARE, Pulizia.Stato.SEGNALATA):
        return False
    if conferma_il_capo(p):
        return utente.pk in capi_del_turno(p)
    return p.turno.dipendente.utente_id == utente.pk


def avvisa_non_eseguibile(utente, p):
    """«Non si può fare» / «Non effettuata»: avvisati i Capi Turno in servizio e il responsabile piazzale."""
    from django.urls import reverse

    from . import manutenzione as mn

    chi = p.fatta_da.nome_breve if p.fatta_da_id else p.turno.dipendente.nome_breve
    mn.avvisa(mn.capiturno_oggi() + resp_piazzale(), utente, f'🧹 Non eseguibile · {p.titolo}', f'{chi}: {p.nota}'[:300],
              reverse('turni:pulizia_voce', args=[p.pk]))


def avvisa_da_rifare(utente, p):
    """«Da rifare»: la notifica a chi la deve confermare (chi la fa, o il Capo Turno per gli OdL dell'Impianto 1)."""
    from . import manutenzione as mn

    chi = capi_del_turno(p) if conferma_il_capo(p) else [p.turno.dipendente.utente_id]
    mn.avvisa(chi, utente, f'🔁 Da rifare · {p.titolo}', p.nota_verifica or 'Va rifatta: guarda la nota nella scheda.',
              link_effettuata(p))


def voce_notturne():
    from .regole_pulizie import NOTTURNE

    return ElementoPulizia.objects.filter(nome=NOTTURNE, attivo=True).first()


def assegna_notturne(utente, turno, nota=''):
    """Le Generiche Notturne a un Capo Turno del Notturno: le assegna il RP entro le 17:00; se il RP è assente,
    le registra il Capo Turno stesso (Giulia, 21/11/2026)."""
    from . import push

    e = voce_notturne()
    if e is None:
        raise ValueError('La voce «Generiche Notturne» non è attiva.')
    if Pulizia.objects.filter(turno=turno, elemento=e).exists():
        raise ValueError(f'Le Generiche Notturne sono già assegnate a {turno.dipendente.nome_breve}.')
    p = Pulizia.objects.create(turno=turno, elemento=e, richiesta_da=utente, nota=(nota or '').strip()[:300])
    if turno.dipendente.utente_id and turno.dipendente.utente_id != utente.pk:
        push.invia([turno.dipendente.utente_id], '🧹 Generiche Notturne', 'Te le assegna il responsabile piazzale: affidale agli OdL e confermale.',
                   f'/turni/pulizie/voce/{p.pk}/', mittente=utente, tipo='pulizia', oggetto_id=p.pk)
    return p
