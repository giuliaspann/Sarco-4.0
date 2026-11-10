"""Archivio: ricerca per periodo, turno e impianto con report PDF (foto comprese), e la scheda storica di ogni dipendente."""

from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from . import saldi
from .models import (FASCE_LAVORATIVE, AnalisiProdotto, Dipendente, Disponibilita, Fascia, FermoImpianto, Intervento, Luogo,
                     Postazione, ProduzioneTurno, Pulizia, Turno)
from .pdf import Documento
from .views import dipendente_di, leggi_data
from .views_messaggi import nome_di
from .views_produzione import puo_vedere
from .views_report import vede_report

TURNI = [('', 'Tutti'), ('1T', '1° turno'), ('2T', '2° turno'), ('N', 'Notturno')]
NOMI_TURNO = dict(TURNI[1:])
MASSIMO_GIORNI = 92
MASSIMO_SCHEDE = 300
IMPIANTI_BASE = [('IMP1', 'Impianto 1'), ('IMP2', 'Impianto 2'), ('METALLI', 'Metalli'), ('SABBIA', 'Sabbia')]
CAMPIONE_IMPIANTO = {'MISTO_IMP1': 'IMP1', 'MEZZO_IMP1': 'IMP1', 'PCV_IMP1': 'IMP1', 'PCV_IMP2': 'IMP2'}


def turno_dell_ora(momento):
    """1° turno 6-14, 2° turno 14-22, notturno 22-6."""
    ora = timezone.localtime(momento).hour
    return '1T' if 6 <= ora < 14 else '2T' if 14 <= ora < 22 else 'N'


def ora(momento):
    return timezone.localtime(momento).strftime('%H:%M') if momento else ''


def chi(utente):
    return nome_di(utente) if utente else ''


def modifica(oggetto):
    """Indirizzo della pagina di modifica nel pannello dell'amministratore."""
    return reverse(f'admin:turni_{oggetto._meta.model_name}_change', args=[oggetto.pk])


def scheda(giorno, momento, turno, impianto, titolo, righe, foto, oggetto=None):
    """Una voce del report, uguale per pagina e PDF. foto: [(didascalia, file, url)]."""
    return {'admin_url': modifica(oggetto) if oggetto else '', 'giorno': giorno, 'ora': ora(momento), 'turno': NOMI_TURNO.get(turno, ''), 'impianto': impianto,
            'titolo': titolo, 'righe': [(e, v) for e, v in righe if v not in (None, '')], 'foto': [f for f in foto if f[1]]}


# ---------------------------------------------------------------- le sezioni
#
# Archivio rifatto (Giulia, 10/11/2026): ogni sezione apre subito la schermata dei filtri; finché non si filtra
# si vede tutto l'archivio, dal più recente. Si tocca una voce per vederla per intero e scaricarne il PDF (con le foto),
# oppure si scarica l'elenco di tutto quello che i filtri restituiscono.

AREE = [('IMPIANTI', 'Impianti'), ('MEZZI', 'Mezzi'), ('PIAZZALE', 'Piazzale')]


def area_luogo(luogo, mezzo=False):
    if mezzo or luogo in (Luogo.MEZZI, Luogo.ESTERNI):
        return 'MEZZI'
    if luogo == Luogo.PIAZZALE:
        return 'PIAZZALE'
    return 'IMPIANTI'


def area_pulizia(p):
    e = p.elemento
    if e:
        if e.tipo == 'MEZZO' or e.luogo in (Luogo.MEZZI, Luogo.ESTERNI):
            return 'MEZZI'
        if e.luogo == Luogo.PIAZZALE:
            return 'PIAZZALE'
        if e.luogo:
            return 'IMPIANTI'
    return 'PIAZZALE' if p.turno.postazione in (Postazione.PIAZZALE, Postazione.PALISTA) else 'IMPIANTI'


def fascia_pulizia(p):
    return Fascia.MATTINA if p.turno.fascia == Fascia.ALTRO else p.turno.fascia


def _pulizie(f):
    q = Pulizia.objects.filter(stato=Pulizia.Stato.VERIFICATA).select_related(
        'turno__dipendente', 'elemento', 'verificata_da__dipendente').order_by('-verificata_il', '-pk')
    if f['dal']:
        q = q.filter(turno__data__range=(f['dal'], f['al']))
    for p in q:
        if f['turno'] and fascia_pulizia(p) != f['turno']:
            continue
        if f['filtro'] and area_pulizia(p) != f['filtro']:
            continue
        yield p


def _scheda_pulizia(p):
    url = reverse('turni:foto', args=[p.pk])
    approvata = ' '.join(x for x in [chi(p.verificata_da), f'il {timezone.localtime(p.verificata_il):%d/%m alle %H:%M}' if p.verificata_il else ''] if x)
    return scheda(p.turno.data, p.fatta_il, fascia_pulizia(p), dict(AREE)[area_pulizia(p)],
                  p.elemento.nome if p.elemento else 'Pulizia',
                  [('Dove', Postazione(p.turno.postazione).label if p.turno.postazione else ''),
                   ('Fatta da', p.turno.dipendente.nome_breve), ('Nota', p.nota),
                   ('Approvata da', approvata), ('Nota di chi ha approvato', p.nota_verifica)],
                  [('Prima', p.foto_prima, url + '?quale=prima'), ('Dopo', p.foto, url)], p)


def _manutenzioni(f):
    """Solo le manutenzioni chiuse."""
    q = Intervento.objects.filter(stato=Intervento.Stato.COMPLETATA).select_related(
        'macchina', 'segnalata_da__dipendente', 'completata_da__dipendente', 'assegnata_a').prefetch_related(
        'altre_foto', 'ricambi_usati__ricambio').order_by('-completata_il', '-pk')
    if f['dal']:
        q = q.filter(completata_il__date__range=(f['dal'], f['al']))
    for i in q:
        quando = i.completata_il or i.segnalata_il
        if f['turno'] and turno_dell_ora(quando) != f['turno']:
            continue
        if f['filtro'] and area_luogo(i.macchina.luogo, i.macchina.tipo == 'MEZZO') != f['filtro']:
            continue
        yield i


def _scheda_manutenzione(i):
    quando = i.completata_il or i.segnalata_il
    foto = [('Guasto', i.foto_guasto, reverse('turni:foto_mn', args=['guasto', i.pk])),
            ('Riparazione', i.foto_riparazione, reverse('turni:foto_mn', args=['riparazione', i.pk]))]
    foto += [('Foto', x.foto, reverse('turni:foto_mn', args=['altra', x.pk])) for x in i.altre_foto.all()]
    pezzi = ', '.join(f'{r.nome} × {r.quantita}' for r in i.ricambi_usati.all())
    return scheda(timezone.localdate(quando), quando, turno_dell_ora(quando), i.macchina.get_luogo_display(),
                  f'{i.macchina.nome} · {i.get_tipo_display()}',
                  [('Problema', i.descrizione),
                   ('Segnalata', ' '.join(x for x in [chi(i.segnalata_da), f'il {timezone.localtime(i.segnalata_il):%d/%m alle %H:%M}'] if x)),
                   ('Assegnata a', i.assegnata_a.nome_breve if i.assegnata_a else ''), ('Lavoro svolto', i.lavoro_svolto),
                   ('Pezzo', i.pezzo), ('Ricambi usati', pezzi),
                   ('Ore di lavoro', f'{i.ore_lavoro:n}'.replace('.', ',') if i.ore_lavoro else ''),
                   ('Officina esterna', i.officina_esterna),
                   ('Chiusa', ' '.join(x for x in [chi(i.completata_da), f'il {timezone.localtime(i.completata_il):%d/%m alle %H:%M}' if i.completata_il else ''] if x))]
                  + _costi(i), foto, i)


def euro(valore):
    return f'€ {valore:,.2f}'.replace(',', ' ').replace('.', ',').replace(' ', '.')


def _costi(i):
    if i.stato != Intervento.Stato.COMPLETATA:
        return []
    c = i.costi
    return [('Costo pezzi', euro(c['pezzi']) if c['pezzi'] else ''), ('Costo ditta esterna', euro(c['esterno']) if c['esterno'] else ''),
            ('Costo totale', euro(c['totale']) if c['totale'] else ''), ('Report esterno', 'allegato nell\'app' if i.report_esterno else '')]


def _produzioni(f):
    q = ProduzioneTurno.objects.prefetch_related('righe__prodotto').select_related('inserita_da__dipendente').order_by('-data', '-inserita_il')
    if f['dal']:
        q = q.filter(data__range=(f['dal'], f['al']))
    if f['turno']:
        q = q.filter(fascia=f['turno'])
    for t in q:
        if f['filtro'] and not any(r.prodotto.impianto == f['filtro'] for r in t.righe.all()):
            continue
        t.solo_impianto = f['filtro']
        yield t


def _scheda_produzione(t):
    righe = [r for r in t.righe.all() if not getattr(t, 'solo_impianto', '') or r.prodotto.impianto == t.solo_impianto]
    impianti = sorted({r.prodotto.get_impianto_display() for r in righe})
    valori = [(r.prodotto.nome, f'{r.tonnellate:n} t'.replace('.', ',')) for r in righe]
    totale = sum((r.tonnellate for r in righe), Decimal('0'))
    return scheda(t.data, None, t.fascia, ', '.join(impianti), f'Produzione · totale {totale:n} t'.replace('.', ','),
                  valori + [('Note', t.note), ('Inserita da', chi(t.inserita_da))],
                  [('Display della pesa', t.foto, reverse('turni:foto_produzione', args=[t.pk]))], t)


def _analisi(f):
    q = AnalisiProdotto.objects.select_related('inserita_da__dipendente').order_by('-inserita_il', '-pk')
    if f['dal']:
        q = q.filter(data__range=(f['dal'], f['al']))
    if f['filtro']:
        q = q.filter(campione=f['filtro'])
    yield from q


def _scheda_analisi(a):
    valori = [(v['nome'], f"{v['g']:n} g" + (f" · {v['gt']:.0f} g/t (limite {v['limite']})" if v['gt'] is not None else '')
               + (' · FUORI LIMITE' if v['fuori'] else '')) for v in a.valori()]
    return scheda(a.data, None, a.fascia, '', a.get_campione_display(),
                  [('Peso del campione', f'{a.peso_kg:n} kg' if a.peso_kg else ''), ('Numero', a.numero)] + valori
                  + [('Note', a.note), ('Inserita da', chi(a.inserita_da))],
                  [('Campione', a.foto, reverse('turni:foto_analisi', args=[a.pk]))], a)


def _fermi(f):
    q = FermoImpianto.objects.select_related('macchina', 'segnalato_da__dipendente', 'ripartenza_da__dipendente').order_by('-fermo_dal', '-pk')
    if f['dal']:
        q = q.filter(fermo_dal__date__range=(f['dal'], f['al']))
    if f['filtro']:
        q = q.filter(impianto=f['filtro'])
    for x in q:
        if f['turno'] and turno_dell_ora(x.fermo_dal) != f['turno']:
            continue
        yield x


def _scheda_fermo(x):
    ripartito = f'alle {ora(x.ripartito_il)}' + (f' del {timezone.localtime(x.ripartito_il):%d/%m}'
                                                 if x.ripartito_il and timezone.localdate(x.ripartito_il) != timezone.localdate(x.fermo_dal) else '')
    return scheda(timezone.localdate(x.fermo_dal), x.fermo_dal, turno_dell_ora(x.fermo_dal), x.get_impianto_display(),
                  f'Fermo · {x.get_causa_display()}',
                  [('Ripartito', ripartito if x.ripartito_il else 'ancora fermo'), ('Durata', x.durata),
                   ('Macchina', x.macchina.nome if x.macchina else ''), ("Cos'è successo", x.descrizione),
                   ('Cosa è stato sistemato', x.sistemazione), ('Segnalato da', chi(x.segnalato_da)),
                   ('Ripartenza registrata da', chi(x.ripartenza_da))],
                  [('Fermo', x.foto, reverse('turni:foto_fermo', args=[x.pk, 'fermo'])),
                   ('Ripartenza', x.foto_ripartenza, reverse('turni:foto_fermo', args=[x.pk, 'ripartenza']))], x)


def _campioni():
    C = AnalisiProdotto.Campione
    nuovi = [C.MISTO_IMP1, C.MEZZO_IMP1, C.MEZZO_PICVISA, C.MEZZO_RW, C.BIANCO_PICVISA, C.BIANCO_RW]
    return [(c.value, c.label) for c in nuovi] + [(v, n) for v, n in C.choices if v not in {c.value for c in nuovi}]


# chiave: titolo, elenco filtrato, scheda di una voce, filtro (etichetta, scelte), turni sì/no, filtro come tasti in alto
SEZIONI = {
    'pulizie': {'titolo': 'Pulizie', 'elenco': _pulizie, 'scheda': _scheda_pulizia, 'filtro': ('Area', AREE), 'turni': True},
    'manutenzione': {'titolo': 'Manutenzione', 'elenco': _manutenzioni, 'scheda': _scheda_manutenzione,
                     'filtro': ('Area', AREE), 'turni': True, 'tasti': True},
    'produzione': {'titolo': 'Produzione', 'elenco': _produzioni, 'scheda': _scheda_produzione,
                   'filtro': ('Impianto', IMPIANTI_BASE[:2]), 'turni': True},
    'analisi': {'titolo': 'Analisi', 'elenco': _analisi, 'scheda': _scheda_analisi, 'filtro': ('Campione', None), 'turni': False},
    'fermi': {'titolo': 'Fermi impianto', 'elenco': _fermi, 'scheda': _scheda_fermo, 'filtro': ('Impianto', IMPIANTI_BASE), 'turni': True},
}
MODELLI = {'pulizie': Pulizia, 'manutenzione': Intervento, 'produzione': ProduzioneTurno, 'analisi': AnalisiProdotto, 'fermi': FermoImpianto}


def scelte_filtro(sezione):
    etichetta, scelte = SEZIONI[sezione]['filtro']
    return etichetta, (scelte if scelte is not None else _campioni())


def leggi_filtri(get, scelte):
    """Senza date si vede tutto l'archivio; con le date al massimo 3 mesi alla volta."""
    dal, al = leggi_data(get.get('dal'), None), leggi_data(get.get('al'), None)
    corto = False
    if dal or al:
        al = al or timezone.localdate()
        dal = dal or al - timedelta(days=MASSIMO_GIORNI - 1)
        if dal > al:
            dal, al = al, dal
        corto = dal < al - timedelta(days=MASSIMO_GIORNI - 1)
        if corto:
            dal = al - timedelta(days=MASSIMO_GIORNI - 1)
    turno = get.get('turno') if get.get('turno') in NOMI_TURNO else ''
    filtro = get.get('filtro') or get.get('impianto') or ''
    filtro = filtro if filtro in dict(scelte) else ''
    parti = []
    if dal:
        parti.append(f'dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}')
    if turno:
        parti.append(f'turno: {NOMI_TURNO[turno]}')
    if filtro:
        parti.append(dict(scelte)[filtro])
    return {'dal': dal, 'al': al, 'turno': turno, 'filtro': filtro, 'accorciato': corto, 'attivi': bool(dal or turno or filtro),
            'descrizione': ' · '.join(parti) or 'tutto l\'archivio'}


def _sezione(request, sezione):
    if not puo_vedere(request.user):
        raise PermissionDenied
    if sezione not in SEZIONI:
        raise Http404
    s = SEZIONI[sezione]
    etichetta, scelte = scelte_filtro(sezione)
    f = leggi_filtri(request.GET, scelte)
    oggetti = []
    for o in s['elenco'](f):
        oggetti.append(o)
        if len(oggetti) > MASSIMO_SCHEDE:
            break
    troppe = len(oggetti) > MASSIMO_SCHEDE
    return s, etichetta, scelte, f, oggetti[:MASSIMO_SCHEDE], troppe


@login_required
def cerca(request, sezione):
    s, etichetta, scelte, f, oggetti, troppe = _sezione(request, sezione)
    voci = []
    for o in oggetti:
        sc = s['scheda'](o)
        sc['pk'] = o.pk
        sc['miniatura'] = sc['foto'][-1][2] if sc['foto'] else ''
        voci.append(sc)
    senza_filtro = request.GET.copy()
    senza_filtro.pop('filtro', None)
    senza_filtro.pop('impianto', None)
    return render(request, 'turni/archivio_cerca.html', {
        'sezione': sezione, 'titolo': s['titolo'], 'f': f, 'turni': TURNI if s['turni'] else None,
        'etichetta': etichetta, 'scelte': scelte, 'tasti': s.get('tasti', False), 'senza_filtro': senza_filtro.urlencode(),
        'voci': voci, 'troppe': troppe, 'massimo': MASSIMO_SCHEDE, 'query': request.GET.urlencode(),
    })


def _risposta_pdf(doc, nome):
    risposta = HttpResponse(doc.pdf(), content_type='application/pdf')
    risposta['Content-Disposition'] = f'attachment; filename="{nome}.pdf"'
    return risposta


def _intestazione(doc, titolo, descrizione, utente):
    doc.testo('SARCO Workspace · Archivio', 9, True, (0.17, 0.48, 0.13))
    doc.testo(titolo, 18, True, (0.05, 0.2, 0.3))
    doc.testo(descrizione, 9.5, False, (0.42, 0.45, 0.5))
    doc.testo(f'Creato il {timezone.localtime():%d/%m/%Y alle %H:%M} da {chi(utente)}', 8.5, False, (0.42, 0.45, 0.5))
    doc.linea()


def _testa(sc):
    return ' · '.join(x for x in [f"{sc['giorno']:%d/%m/%Y}", sc['ora'], sc['turno'], sc['impianto']] if x)


@login_required
def scarica(request, sezione):
    """Il PDF in formato elenco di tutto quello che i filtri restituiscono."""
    s, etichetta, scelte, f, oggetti, troppe = _sezione(request, sezione)
    doc = Documento(f'Archivio {s["titolo"].lower()}')
    _intestazione(doc, f'Archivio {s["titolo"].lower()} · elenco', f['descrizione'] + f' · {len(oggetti)} risultati', request.user)
    if troppe:
        doc.testo(f'Mostrati i primi {MASSIMO_SCHEDE} risultati: restringi i filtri per vederli tutti.', 9, True, (0.7, 0.35, 0))
    if not oggetti:
        doc.testo('Nessun risultato con questi filtri.', 11)
    else:
        righe = []
        for o in oggetti:
            sc = s['scheda'](o)
            dettagli = ' · '.join(f'{e}: {v}' for e, v in sc['righe'][:3])
            righe.append([f"{sc['giorno']:%d/%m/%Y}" + (f" {sc['ora']}" if sc['ora'] else ''), sc['turno'], sc['impianto'],
                          sc['titolo'], dettagli])
        doc.tabella(['Giorno', 'Turno', etichetta if etichetta != 'Campione' else 'Area', 'Cosa', 'Dettagli'], righe,
                    [0.15, 0.1, 0.13, 0.22, 0.40], corpo=8.5)
    return _risposta_pdf(doc, f'Archivio {s["titolo"].lower()} elenco {timezone.localdate():%Y-%m-%d}')


def _voce(request, sezione, pk):
    if not puo_vedere(request.user):
        raise PermissionDenied
    if sezione not in SEZIONI:
        raise Http404
    s = SEZIONI[sezione]
    o = get_object_or_404(MODELLI[sezione], pk=pk)
    # solo quello che è davvero in archivio (pulizie approvate, manutenzioni chiuse)
    if sezione == 'pulizie' and o.stato != Pulizia.Stato.VERIFICATA or sezione == 'manutenzione' and o.stato != Intervento.Stato.COMPLETATA:
        raise Http404
    return s, o, s['scheda'](o)


@login_required
def voce(request, sezione, pk):
    s, o, sc = _voce(request, sezione, pk)
    return render(request, 'turni/archivio_voce.html', {'sezione': sezione, 'titolo': s['titolo'], 's': sc, 'pk': pk,
                                                         'indietro': request.GET.urlencode()})


@login_required
def voce_pdf(request, sezione, pk):
    """Il PDF di una sola voce, con le foto allegate."""
    s, o, sc = _voce(request, sezione, pk)
    doc = Documento(f'{s["titolo"]} {sc["titolo"]}')
    _intestazione(doc, sc['titolo'], f'{s["titolo"]} · {_testa(sc)}', request.user)
    for etichetta, valore in sc['righe']:
        doc.voce(etichetta, valore)
    if sc['foto']:
        doc.spazio(6)
        doc.foto([(d, file) for d, file, _ in sc['foto']])
    return _risposta_pdf(doc, f'{s["titolo"]} {sc["giorno"]:%Y-%m-%d} {sc["titolo"]}'.replace('/', '-'))


@login_required
def inventario(request):
    """Mezzi, componenti, piazzale e ricambi in un unico tasto (Giulia, 10/11)."""
    if not puo_vedere(request.user):
        raise PermissionDenied
    return render(request, 'turni/inventario.html')


# ---------------------------------------------------------------- dipendenti


@login_required
def dipendenti(request):
    """L'ufficio e la direzione vedono tutti; il dipendente vede solo la propria scheda."""
    if not vede_report(request.user):
        dip = dipendente_di(request)
        if dip is None:
            raise PermissionDenied
        return redirect('turni:archivio_dipendente', dip.pk)
    cerca_nome = (request.GET.get('q') or '').strip()
    elenco = Dipendente.objects.filter(attivo=True)
    if cerca_nome:
        elenco = elenco.filter(nome__icontains=cerca_nome)
    return render(request, 'turni/archivio_dipendenti.html', {'elenco': elenco, 'q': cerca_nome})


def periodi_dipendente(oggi):
    inizio = oggi.replace(day=1)
    fine_scorso = inizio - timedelta(days=1)
    return [('mese', 'Questo mese', inizio, oggi), ('scorso', 'Mese scorso', fine_scorso.replace(day=1), fine_scorso),
            ('anno', "Quest'anno", oggi.replace(month=1, day=1), oggi)]


def storico(dip, dal, al):
    """Tutto quello che ha fatto una persona nel periodo. Le ore sono una stima dai turni (8 ore a turno)."""
    utente = dip.utente
    oggi = timezone.localdate()
    turni = list(dip.turni.filter(data__range=(dal, min(al, oggi))).order_by('data'))
    lavorati = [t for t in turni if t.fascia in FASCE_LAVORATIVE]
    per_fascia = Counter(t.fascia for t in lavorati)
    extra = list(Disponibilita.objects.filter(dipendente=dip, confermata=True, extra__data__range=(dal, al))
                 .select_related('extra').order_by('extra__data'))
    pulizie_fatte = list(Pulizia.objects.filter(turno__dipendente=dip, turno__data__range=(dal, al),
                                                stato__in=[Pulizia.Stato.FATTA, Pulizia.Stato.VERIFICATA])
                         .select_related('elemento', 'turno').order_by('turno__data'))
    da_rifare = Pulizia.objects.filter(turno__dipendente=dip, turno__data__range=(dal, al), stato=Pulizia.Stato.SEGNALATA).count()
    manutenzioni = Intervento.objects.filter(stato=Intervento.Stato.COMPLETATA, completata_il__date__range=(dal, al))
    manutenzioni = manutenzioni.filter(Q(assegnata_a=dip) | Q(collaboratori=dip) | (Q(completata_da=utente) if utente else Q(pk=None)))
    manutenzioni = list(manutenzioni.distinct().select_related('macchina').order_by('completata_il'))
    segnalazioni, fermi_segnalati, analisi_fatte = [], [], []
    if utente:
        segnalazioni = list(Intervento.objects.filter(segnalata_da=utente, segnalata_il__date__range=(dal, al))
                            .exclude(tipo=Intervento.Tipo.LAVORO).select_related('macchina').order_by('segnalata_il'))
        fermi_segnalati = list(FermoImpianto.objects.filter(segnalato_da=utente, fermo_dal__date__range=(dal, al)).order_by('fermo_dal'))
        analisi_fatte = list(AnalisiProdotto.objects.filter(inserita_da=utente, data__range=(dal, al)).order_by('data'))
    ore = len(lavorati) * saldi.ORE_GIORNO
    ore_extra = len(extra) * saldi.ORE_GIORNO
    return {
        'turni': lavorati, 'per_fascia': [(Turno.SIGLE.get(f, f), Fascia(f).label, n) for f, n in per_fascia.most_common()],
        'ore': ore, 'extra': extra, 'ore_extra': ore_extra,
        'assenze': sum(1 for t in turni if t.fascia in (Fascia.FERIE, Fascia.PERMESSO)),
        'pulizie': pulizie_fatte, 'da_rifare': da_rifare, 'manutenzioni': manutenzioni,
        'ore_manutenzione': sum((i.ore_lavoro or 0 for i in manutenzioni), Decimal('0')),
        'segnalazioni': segnalazioni, 'fermi': fermi_segnalati, 'n_segnalazioni': len(segnalazioni) + len(fermi_segnalati),
        'analisi': analisi_fatte,
        'saldo': saldi.residuo(dip),
    }


def _dipendente(request, dip_id):
    dip = get_object_or_404(Dipendente, pk=dip_id)
    if not (vede_report(request.user) or dip == dipendente_di(request)):
        raise PermissionDenied
    oggi = timezone.localdate()
    scelte = periodi_dipendente(oggi)
    chiave = request.GET.get('periodo', '')
    scelta = next((p for p in scelte if p[0] == chiave), None)
    if scelta:
        dal, al = scelta[2], scelta[3]
    else:
        al = leggi_data(request.GET.get('al'), oggi)
        dal = leggi_data(request.GET.get('dal'), oggi.replace(day=1))
        dal, al = min(dal, al), max(dal, al)
        chiave = '' if request.GET.get('dal') else 'mese'
    return dip, dal, al, scelte, chiave


@login_required
def dipendente(request, dip_id):
    dip, dal, al, scelte, chiave = _dipendente(request, dip_id)
    return render(request, 'turni/archivio_dipendente.html', {
        'dip': dip, 'dal': dal, 'al': al, 'scelte': scelte, 'chiave': chiave, 's': storico(dip, dal, al),
        'tutti': vede_report(request.user), 'query': request.GET.urlencode(),
    })


@login_required
def dipendente_pdf(request, dip_id):
    dip, dal, al, _, _ = _dipendente(request, dip_id)
    s = storico(dip, dal, al)
    doc = Documento(f'{dip.nome_breve} {dal:%d/%m}-{al:%d/%m/%Y}')
    _intestazione(doc, dip.nome_breve, f'Dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}' + (f' · {dip.mansioni_display}' if dip.mansioni else ''),
                  request.user)
    doc.testo('Riepilogo', 12, True, (0.05, 0.2, 0.3))
    doc.voce('Turni lavorati', f"{len(s['turni'])}" + (' (' + ', '.join(f'{n} {nome}' for _, nome, n in s['per_fascia']) + ')'
                                                       if s['per_fascia'] else ''))
    doc.voce('Ore di lavoro (stima)', f"{s['ore']:n} h · 8 ore per turno, in attesa dei dati del badge")
    doc.voce('Straordinari', f"{len(s['extra'])} turni extra confermati · {s['ore_extra']:n} h")
    doc.voce('Giorni di ferie o permesso', s['assenze'])
    doc.voce('Pulizie fatte', f"{len(s['pulizie'])}" + (f" · {s['da_rifare']} da rifare" if s['da_rifare'] else ''))
    doc.voce('Manutenzioni fatte', f"{len(s['manutenzioni'])} · {s['ore_manutenzione']:n} h dichiarate")
    doc.voce('Segnalazioni fatte', f"{len(s['segnalazioni'])} guasti · {len(s['fermi'])} fermi impianto")
    doc.voce('Analisi fatte', len(s['analisi']))
    # il saldo di ferie e ROL non si mostra più (Giulia, 10/11/2026)
    elenchi = [
        ('Turni', [f'{t.data:%d/%m} · {t.get_fascia_display()}' + (f' · {t.get_postazione_display()}' if t.postazione else '')
                   + (' · Capo Turno' if t.capoturno else '') for t in s['turni']]),
        ('Straordinari', [f'{d.extra.data:%d/%m} · {d.extra.get_fascia_display()}' for d in s['extra']]),
        ('Pulizie', [f'{p.turno.data:%d/%m} · {p.elemento.nome if p.elemento else "Pulizia"} · {p.get_stato_display()}'
                     for p in s['pulizie']]),
        ('Manutenzioni', [f'{timezone.localtime(i.completata_il):%d/%m} · {i.macchina.nome}'
                          + (f' · {i.ore_lavoro:n} h' if i.ore_lavoro else '') + (f' · {i.lavoro_svolto}' if i.lavoro_svolto else '')
                          for i in s['manutenzioni']]),
        ('Segnalazioni', [f'{timezone.localtime(i.segnalata_il):%d/%m} · {i.macchina.nome} · {i.descrizione}' for i in s['segnalazioni']]
         + [f'{timezone.localtime(f.fermo_dal):%d/%m} · Fermo {f.get_impianto_display()} · {f.get_causa_display()}' for f in s['fermi']]),
        ('Analisi', [f'{a.data:%d/%m} · {a.get_campione_display()}' + (' · fuori limite' if a.fuori_limite else '') for a in s['analisi']]),
    ]
    for titolo, righe in elenchi:
        if righe:
            doc.linea()
            doc.testo(f'{titolo} ({len(righe)})', 12, True, (0.05, 0.2, 0.3))
            for r in righe:
                doc.testo(r, 9.5)
    return _risposta_pdf(doc, f'{dip.nome_breve} {dal:%Y-%m-%d} - {al:%Y-%m-%d}')


# ---------------------------------------------------------------- componenti


@login_required
def componenti(request):
    """Per ogni macchinario e mezzo, i ricambi che gli appartengono (con scorta e posto in magazzino)."""
    from .models import Macchina

    if not puo_vedere(request.user):
        raise PermissionDenied
    q = (request.GET.get('q') or '').strip()
    elenco = Macchina.objects.filter(attiva=True).exclude(tipo=Macchina.Tipo.SEGNALETICA).prefetch_related('ricambi')
    if q:
        elenco = elenco.filter(Q(nome__icontains=q) | Q(codice__icontains=q) | Q(ricambi__nome__icontains=q)).distinct()
    return render(request, 'turni/archivio_componenti.html', {'elenco': elenco, 'q': q})
