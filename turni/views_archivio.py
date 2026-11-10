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
CAMPIONE_IMPIANTO = {'MISTO_IMP1': 'IMP1', 'PCV_IMP1': 'IMP1', 'PCV_IMP2': 'IMP2'}


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


def pulizie(dal, al, turno, impianto):
    q = Pulizia.objects.filter(stato=Pulizia.Stato.VERIFICATA, turno__data__range=(dal, al)).select_related(
        'turno__dipendente', 'elemento', 'verificata_da__dipendente').order_by('turno__data', 'fatta_il')
    if impianto:
        q = q.filter(turno__postazione=impianto)
    for p in q:
        fascia = Fascia.MATTINA if p.turno.fascia == Fascia.ALTRO else p.turno.fascia
        if turno and fascia != turno:
            continue
        url = reverse('turni:foto', args=[p.pk])
        yield scheda(p.turno.data, p.fatta_il, fascia, Postazione(p.turno.postazione).label if p.turno.postazione else '',
                     p.elemento.nome if p.elemento else 'Pulizia',
                     [('Fatta da', p.turno.dipendente.nome_breve), ('Nota', p.nota),
                      ('Approvata da', chi(p.verificata_da)), ('Nota del Capo Turno', p.nota_verifica)],
                     [('Prima', p.foto_prima, url + '?quale=prima'), ('Dopo', p.foto, url)], p)


def manutenzione(dal, al, turno, impianto):
    q = Intervento.objects.filter(Q(segnalata_il__date__range=(dal, al)) | Q(completata_il__date__range=(dal, al))).exclude(
        stato=Intervento.Stato.RIFIUTATA).select_related('macchina', 'segnalata_da__dipendente', 'completata_da__dipendente',
                                                         'assegnata_a').prefetch_related(
        'altre_foto', 'ricambi_usati__ricambio').order_by('segnalata_il')
    if impianto:
        q = q.filter(macchina__luogo=impianto)
    for i in q:
        quando = i.completata_il or i.segnalata_il
        if turno and turno_dell_ora(quando) != turno:
            continue
        foto = [('Guasto', i.foto_guasto, reverse('turni:foto_mn', args=['guasto', i.pk])),
                ('Riparazione', i.foto_riparazione, reverse('turni:foto_mn', args=['riparazione', i.pk]))]
        foto += [('Foto', f.foto, reverse('turni:foto_mn', args=['altra', f.pk])) for f in i.altre_foto.all()]
        yield scheda(timezone.localdate(quando), quando, turno_dell_ora(quando), i.macchina.get_luogo_display(),
                     f'{i.macchina.nome} · {i.get_tipo_display()}',
                     [('Stato', i.get_stato_display()), ('Problema', i.descrizione),
                      ('Segnalata', ' '.join(x for x in [chi(i.segnalata_da), f'il {timezone.localtime(i.segnalata_il):%d/%m alle %H:%M}'] if x)),
                      ('Assegnata a', i.assegnata_a.nome_breve if i.assegnata_a else ''), ('Lavoro svolto', i.lavoro_svolto),
                      ('Pezzo', i.pezzo), ('Ore di lavoro', f'{i.ore_lavoro:n}'.replace('.', ',') if i.ore_lavoro else ''), ('Officina esterna', i.officina_esterna),
                      ('Chiusa da', chi(i.completata_da))] + _costi(i), foto, i)


def euro(valore):
    return f'€ {valore:,.2f}'.replace(',', ' ').replace('.', ',').replace(' ', '.')


def _costi(i):
    if i.stato != Intervento.Stato.COMPLETATA:
        return []
    c = i.costi
    return [('Costo pezzi', euro(c['pezzi']) if c['pezzi'] else ''), ('Costo ditta esterna', euro(c['esterno']) if c['esterno'] else ''),
            ('Costo totale', euro(c['totale']) if c['totale'] else ''), ('Report esterno', 'allegato nell\'app' if i.report_esterno else '')]


def produzione(dal, al, turno, impianto):
    q = ProduzioneTurno.objects.filter(data__range=(dal, al)).select_related('inserita_da__dipendente').prefetch_related(
        'righe__prodotto').order_by('data', 'fascia')
    if turno:
        q = q.filter(fascia=turno)
    for t in q:
        righe = [r for r in t.righe.all() if not impianto or r.prodotto.impianto == impianto]
        if not righe:
            continue
        impianti = sorted({r.prodotto.get_impianto_display() for r in righe})
        valori = [(r.prodotto.nome, f'{r.tonnellate:n} t'.replace('.', ',')) for r in righe]
        totale = sum((r.tonnellate for r in righe), Decimal('0'))
        yield scheda(t.data, None, t.fascia, ', '.join(impianti), f'Produzione · totale {totale:n} t'.replace('.', ','),
                     valori + [('Note', t.note), ('Inserita da', chi(t.inserita_da))],
                     [('Display della pesa', t.foto, reverse('turni:foto_produzione', args=[t.pk]))], t)


def analisi(dal, al, turno, impianto):
    q = AnalisiProdotto.objects.filter(data__range=(dal, al)).select_related('inserita_da__dipendente').order_by('data', 'pk')
    if turno:
        q = q.filter(fascia=turno)
    for a in q:
        imp = CAMPIONE_IMPIANTO.get(a.campione, '')
        if impianto and imp != impianto:
            continue
        valori = [(v['nome'], f"{v['g']:n} g" + (f" · {v['gt']:.0f} g/t (limite {v['limite']})" if v['gt'] is not None else '')
                   + (' · FUORI LIMITE' if v['fuori'] else '')) for v in a.valori()]
        yield scheda(a.data, None, a.fascia, dict(IMPIANTI_BASE).get(imp, ''), a.get_campione_display(),
                     [('Peso del campione', f'{a.peso_kg:n} kg' if a.peso_kg else ''), ('Numero', a.numero)] + valori
                     + [('Note', a.note), ('Inserita da', chi(a.inserita_da))],
                     [('Campione', a.foto, reverse('turni:foto_analisi', args=[a.pk]))], a)


def fermi(dal, al, turno, impianto):
    q = FermoImpianto.objects.filter(fermo_dal__date__range=(dal, al)).select_related(
        'macchina', 'segnalato_da__dipendente', 'ripartenza_da__dipendente').order_by('fermo_dal')
    if impianto:
        q = q.filter(impianto=impianto)
    for f in q:
        if turno and turno_dell_ora(f.fermo_dal) != turno:
            continue
        ripartito = f'alle {ora(f.ripartito_il)}' + (f' del {timezone.localtime(f.ripartito_il):%d/%m}'
                                                     if timezone.localdate(f.ripartito_il) != timezone.localdate(f.fermo_dal) else '')
        yield scheda(timezone.localdate(f.fermo_dal), f.fermo_dal, turno_dell_ora(f.fermo_dal), f.get_impianto_display(),
                     f'Fermo · {f.get_causa_display()}',
                     [('Ripartito', ripartito if f.ripartito_il else 'ancora fermo'), ('Durata', f.durata),
                      ('Macchina', f.macchina.nome if f.macchina else ''), ("Cos'è successo", f.descrizione),
                      ('Cosa è stato sistemato', f.sistemazione), ('Segnalato da', chi(f.segnalato_da)),
                      ('Ripartenza registrata da', chi(f.ripartenza_da))],
                     [('Fermo', f.foto, reverse('turni:foto_fermo', args=[f.pk, 'fermo'])),
                      ('Ripartenza', f.foto_ripartenza, reverse('turni:foto_fermo', args=[f.pk, 'ripartenza']))], f)


# chiave: (titolo, funzione, impianti tra cui scegliere, pagina della sezione)
SEZIONI = {
    'pulizie': ('Pulizie', pulizie, IMPIANTI_BASE + [('PIAZZALE', 'Piazzale')], 'turni:archivio_pulizie'),
    'manutenzione': ('Manutenzione', manutenzione, IMPIANTI_BASE + [(v, n) for v, n in Luogo.choices if v not in ('IMP1', 'IMP2', 'METALLI', 'SABBIA')],
                     'turni:interventi'),
    'produzione': ('Dati produzione', produzione, IMPIANTI_BASE[:2], 'turni:produzione'),
    'analisi': ('Analisi', analisi, IMPIANTI_BASE[:2], 'turni:archivio_analisi'),
    'fermi': ('Fermi impianto', fermi, IMPIANTI_BASE, 'turni:fermi'),
}


def leggi_filtri(get, impianti, predefinito_giorni=7):
    oggi = timezone.localdate()
    al = leggi_data(get.get('al'), oggi)
    dal = leggi_data(get.get('dal'), al - timedelta(days=predefinito_giorni - 1))
    if dal > al:
        dal, al = al, dal
    corto = dal < al - timedelta(days=MASSIMO_GIORNI - 1)
    if corto:
        dal = al - timedelta(days=MASSIMO_GIORNI - 1)
    turno = get.get('turno') if get.get('turno') in NOMI_TURNO else ''
    impianto = get.get('impianto') if get.get('impianto') in dict(impianti) else ''
    return {'dal': dal, 'al': al, 'turno': turno, 'impianto': impianto, 'accorciato': corto,
            'descrizione': f"dal {dal:%d/%m/%Y} al {al:%d/%m/%Y} · turno: {NOMI_TURNO.get(turno, 'tutti')}"
                           f" · impianto: {dict(impianti).get(impianto, 'tutti')}"}


def _sezione(request, sezione):
    if not puo_vedere(request.user):
        raise PermissionDenied
    if sezione not in SEZIONI:
        raise Http404
    titolo, funzione, impianti, pagina = SEZIONI[sezione]
    f = leggi_filtri(request.GET, impianti)
    schede = []
    for s in funzione(f['dal'], f['al'], f['turno'], f['impianto']):
        schede.append(s)
        if len(schede) > MASSIMO_SCHEDE:
            break
    troppe = len(schede) > MASSIMO_SCHEDE
    return titolo, impianti, pagina, f, schede[:MASSIMO_SCHEDE], troppe


@login_required
def cerca(request, sezione):
    titolo, impianti, pagina, f, schede, troppe = _sezione(request, sezione)
    return render(request, 'turni/archivio_cerca.html', {
        'sezione': sezione, 'titolo': titolo, 'pagina': pagina, 'f': f, 'turni': TURNI, 'impianti': impianti,
        'schede': schede, 'troppe': troppe, 'massimo': MASSIMO_SCHEDE, 'query': request.GET.urlencode(),
    })


def _risposta_pdf(doc, nome):
    risposta = HttpResponse(doc.pdf(), content_type='application/pdf')
    risposta['Content-Disposition'] = f'attachment; filename="{nome}.pdf"'
    return risposta


def _intestazione(doc, titolo, descrizione, utente):
    doc.testo('SARCO 4.0 · Archivio', 9, True, (0.17, 0.48, 0.13))
    doc.testo(titolo, 18, True, (0.05, 0.2, 0.3))
    doc.testo(descrizione, 9.5, False, (0.42, 0.45, 0.5))
    doc.testo(f'Creato il {timezone.localtime():%d/%m/%Y alle %H:%M} da {chi(utente)}', 8.5, False, (0.42, 0.45, 0.5))
    doc.linea()


@login_required
def scarica(request, sezione):
    titolo, impianti, pagina, f, schede, troppe = _sezione(request, sezione)
    doc = Documento(f'Archivio {titolo.lower()} {f["dal"]:%d/%m}-{f["al"]:%d/%m/%Y}')
    _intestazione(doc, f'Archivio {titolo.lower()}', f['descrizione'] + f' · {len(schede)} risultati', request.user)
    if troppe:
        doc.testo(f'Mostrati i primi {MASSIMO_SCHEDE} risultati: restringi il periodo per vederli tutti.', 9, True, (0.7, 0.35, 0))
    if not schede:
        doc.testo('Nessun risultato con questi filtri.', 11)
    for s in schede:
        doc.spazio(4)
        testa = ' · '.join(x for x in [f"{s['giorno']:%d/%m/%Y}", s['ora'], s['turno'], s['impianto']] if x)
        doc.testo(testa, 8.5, True, (0.17, 0.48, 0.13))
        doc.testo(s['titolo'], 11.5, True, (0.05, 0.2, 0.3))
        for etichetta, valore in s['righe']:
            doc.voce(etichetta, valore)
        doc.foto([(d, file) for d, file, _ in s['foto']])
        doc.linea()
    return _risposta_pdf(doc, f'Archivio {titolo.lower()} {f["dal"]:%Y-%m-%d} - {f["al"]:%Y-%m-%d}')


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
