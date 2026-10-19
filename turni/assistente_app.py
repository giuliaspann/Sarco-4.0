"""Il resto dell'app per l'assistente: manutenzione, pulizie, statistiche, messaggi, turni extra.

Stesso schema di assistente.py: gli strumenti che leggono rispondono subito, quelli "proponi_" preparano
l'azione e partono solo dopo il tasto Conferma. Le foto arrivano dal tasto 📷 della chat.
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.urls import reverse
from django.utils import timezone

from . import manutenzione as mn
from . import richieste as svc
from .models import (
    INQUINANTI, AnalisiProdotto, CambioTurno, ElementoPulizia, FermoImpianto, Intervento, Macchina, ModificaTurno,
    ProdottoProduzione, ProduzioneTurno, Pulizia, RigaProduzione, TurnoExtra,
)


class Errore(Exception):
    pass


NUM = {'type': ['number', 'null']}
DATA = {'type': 'string', 'description': 'AAAA-MM-GG'}
ORA = {'type': 'string', 'description': 'HH:MM, oppure stringa vuota = adesso'}
SERVE_FOTO = {'proponi_guasto', 'proponi_completamento_manutenzione', 'proponi_impedimento_pulizia'}


def _s(nome, descrizione, proprieta=None, richiesti=None):
    proprieta = proprieta or {}
    return {'name': nome, 'description': descrizione, 'input_schema': {
        'type': 'object', 'properties': proprieta, 'required': richiesti if richiesti is not None else list(proprieta)}}


def _tipi_lavoro():
    return dict(Intervento._meta.get_field('tipo_lavoro').choices)


def strumenti(utente):
    dip = getattr(utente, 'dipendente', None)
    t = [
        _s('elenco_macchine', 'Cerca macchine, mezzi e attrezzature (per nome o luogo) e dà il loro id.',
           {'cerca': {'type': 'string'}}),
        _s('fermi_in_corso', 'Impianti fermi adesso, con id del fermo.'),
        _s('interventi_aperti', 'Guasti e manutenzioni ancora aperti.'),
        _s('bacheca', 'Ultimi avvisi della bacheca aziendale.'),
        _s('report_statistiche', 'Riassunto di produzione e analisi del laboratorio.',
           {'giorni': {'type': 'integer', 'enum': [7, 30, 90]}}),
        _s('proponi_fermo', 'Prepara la segnalazione di un fermo impianto (ripartito_alle vuoto se è ancora fermo; '
           'macchina_id 0 se non si sa quale macchina).',
           {'impianto': {'type': 'string', 'enum': [v for v, _ in FermoImpianto.IMPIANTI]},
            'causa': {'type': 'string', 'enum': list(FermoImpianto.Causa.values)},
            'macchina_id': {'type': 'integer'}, 'descrizione': {'type': 'string'}, 'giorno': DATA, 'dalle': ORA,
            'ripartito_alle': ORA}),
        _s('proponi_ripartenza', 'Prepara la ripartenza di un impianto fermo (id da fermi_in_corso).',
           {'fermo_id': {'type': 'integer'}, 'alle': ORA, 'sistemazione': {'type': 'string'}}),
        _s('proponi_guasto', 'Prepara la segnalazione di un guasto o di una necessità di manutenzione su una macchina. '
           'Serve una foto allegata con 📷.',
           {'macchina_id': {'type': 'integer'}, 'descrizione': {'type': 'string'}, 'macchina_ferma': {'type': 'boolean'}}),
        _s('proponi_completamento_manutenzione', 'Prepara la registrazione di una manutenzione già fatta (pezzo sistemato, '
           'sostituito, montato, controllo). Serve una foto allegata con 📷. ore = 0 se non si sa.',
           {'macchina_id': {'type': 'integer'}, 'cosa_fatto': {'type': 'string'},
            'tipo_lavoro': {'type': 'string', 'enum': [''] + list(_tipi_lavoro())}, 'pezzo': {'type': 'string'},
            'ore': {'type': 'number'}}),
        _s('elenco_pulizie', 'Le pulizie del turno di chi scrive (con id e stato) e cosa si può pulire.'),
        _s('proponi_pulizia_fatta', 'Prepara il completamento di una pulizia assegnata (id da elenco_pulizie). '
           'Se c\'è una foto allegata diventa la foto "dopo".', {'pulizia_id': {'type': 'integer'}, 'nota': {'type': 'string'}}),
        _s('proponi_pulizia_aggiuntiva', 'Prepara una pulizia fatta in più, non assegnata.',
           {'cosa': {'type': 'string', 'description': 'nome del mezzo o della zona'}, 'nota': {'type': 'string'}}),
        _s('proponi_richiesta_pulizia', 'Prepara la richiesta di una pulizia a un collega in turno adesso.',
           {'collega': {'type': 'string'}, 'cosa': {'type': 'string'}, 'nota': {'type': 'string'}}),
        _s('proponi_impedimento_pulizia', 'Prepara la segnalazione che una pulizia non si può fare. Serve una foto del motivo.',
           {'pulizia_id': {'type': 'integer'}, 'motivo': {'type': 'string', 'enum': Pulizia.MOTIVI_IMPEDIMENTO},
            'nota': {'type': 'string'}}),
        _s('proponi_produzione', 'Prepara la produzione di fine turno letta sul display della pesa (tonnellate per codice).',
           {'giorno': DATA, 'fascia': {'type': 'string', 'enum': ['1T', '2T', 'N']},
            'righe': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'codice': {'type': 'string'}, 'tonnellate': {'type': 'number'}}, 'required': ['codice', 'tonnellate']}},
            'note': {'type': 'string'}}),
        _s('proponi_analisi', 'Prepara un\'analisi di laboratorio: peso del campione in kg e GRAMMI di ogni inquinante '
           '(null se non misurato).',
           {'giorno': DATA, 'fascia': {'type': 'string', 'enum': ['', '1T', '2T', 'N']},
            'campione': {'type': 'string', 'enum': list(AnalisiProdotto.Campione.values)}, 'peso_kg': NUM, 'numero': NUM,
            **{c: NUM for c, _, _ in INQUINANTI}, 'note': {'type': 'string'}}),
        _s('proponi_messaggio_chat', 'Prepara un messaggio in una chat di gruppo dell\'app.',
           {'chat': {'type': 'string'}, 'testo': {'type': 'string'}}),
    ]
    if dip:
        t += [
            _s('turni_extra', 'Turni in più per cui l\'ufficio cerca volontari, con id.'),
            _s('proponi_disponibilita', 'Prepara la risposta a un turno extra (id da turni_extra).',
               {'extra_id': {'type': 'integer'}, 'disponibile': {'type': 'boolean'}}),
            _s('proponi_risposta_cambio', 'Prepara la risposta a un collega che chiede di cambiare turno (id da le_mie_richieste).',
               {'cambio_id': {'type': 'integer'}, 'accetta': {'type': 'boolean'}}),
            _s('proponi_presa_visione', 'Prepara la presa visione dei turni cambiati dall\'ufficio.'),
        ]
    if mn.puo_chiedere_pezzi(utente):
        t.append(_s('proponi_programma_manutenzione', 'Prepara una manutenzione programmata (ogni_giorni 0 = una volta).',
                    {'macchina_id': {'type': 'integer'}, 'attivita': {'type': 'string'}, 'giorno': DATA,
                     'ogni_giorni': {'type': 'integer', 'enum': [0, 7, 14, 30, 90, 180, 365]}}))
    if svc.e_responsabile(utente):
        t.append(_s('proponi_annuncio', 'Prepara un avviso in bacheca per tutti.',
                    {'testo': {'type': 'string'}, 'importante': {'type': 'boolean'}}))
    return t


NOMI = {'elenco_macchine', 'fermi_in_corso', 'interventi_aperti', 'bacheca', 'report_statistiche', 'elenco_pulizie',
        'turni_extra'}


def gestisce(nome):
    return nome in NOMI or nome in AZIONI


# ---------------------------------------------------------------- aiuti


def _data(testo):
    try:
        return date.fromisoformat(testo)
    except (TypeError, ValueError):
        raise Errore(f'Data non valida: {testo}')


def _momento(giorno, ora):
    """Data + ora in un momento preciso; ora vuota = adesso."""
    if not ora:
        return timezone.now()
    try:
        t = time.fromisoformat(ora)
    except ValueError:
        raise Errore(f'Ora non valida: {ora}')
    return timezone.make_aware(datetime.combine(_data(giorno) if giorno else timezone.localdate(), t))


def _macchina(pk):
    m = Macchina.objects.filter(pk=pk, attiva=True).first()
    if not m:
        raise Errore('Macchina non trovata: cerca prima con elenco_macchine.')
    return m


def _dip(utente):
    dip = getattr(utente, 'dipendente', None)
    if not dip:
        raise Errore('Non sei collegato a un dipendente.')
    return dip


def _turno(utente):
    from .pulizie import genera_pulizie, turno_attuale

    t = turno_attuale(_dip(utente))
    if not t or not t.lavora:
        raise Errore('Adesso non sei in turno.')
    genera_pulizie(t)
    return t


def _pulizia(utente, pk):
    p = _turno(utente).pulizie.filter(pk=pk).select_related('elemento').first()
    if not p:
        raise Errore('Pulizia non trovata: guarda elenco_pulizie.')
    if p.stato == Pulizia.Stato.VERIFICATA:
        raise Errore('Questa pulizia è già stata verificata.')
    return p


def _elemento(nome):
    parole = [p for p in (nome or '').lower().split() if len(p) > 1]
    qs = ElementoPulizia.objects.filter(attivo=True)
    for p in parole:
        qs = qs.filter(nome__icontains=p)
    trovati = list(qs[:5])
    if len(trovati) != 1:
        tutti = ', '.join(ElementoPulizia.objects.filter(attivo=True).values_list('nome', flat=True))
        raise Errore(f'Non so quale pulizia: scegli tra {tutti}.')
    return trovati[0]


def _numero(v):
    if v is None or v == '':
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        raise Errore(f'Numero non valido: {v}')
    if d < 0 or d > 1000000:
        raise Errore(f'Numero fuori misura: {v}')
    return d


def _ora(dt):
    return timezone.localtime(dt).strftime('%H:%M')


# ---------------------------------------------------------------- letture


def leggi(nome, dati, utente):
    if nome == 'elenco_macchine':
        qs = Macchina.objects.filter(attiva=True)
        for p in [p for p in (dati.get('cerca') or '').split() if len(p) > 1]:
            qs = qs.filter(nome__icontains=p) | Macchina.objects.filter(attiva=True, codice__icontains=p)
        return '\n'.join(f'id={m.pk}: {m.nome} ({m.get_luogo_display()})' for m in qs.distinct()[:20]) or 'nessuna macchina trovata'
    if nome == 'fermi_in_corso':
        return '\n'.join(f'id={f.pk}: {f.get_impianto_display()} fermo dalle {_ora(f.fermo_dal)} · {f.get_causa_display()}'
                         for f in FermoImpianto.objects.filter(ripartito_il__isnull=True)) or 'nessun impianto fermo'
    if nome == 'interventi_aperti':
        qs = Intervento.objects.filter(stato__in=Intervento.APERTI).select_related('macchina')[:15]
        return '\n'.join(f'{i.macchina.nome}: {i.descrizione[:70]} ({i.get_stato_display()})' for i in qs) or 'nessuno'
    if nome == 'bacheca':
        from .models import Annuncio

        return '\n'.join(f'{timezone.localtime(a.creato_il):%d/%m}: {a.testo[:200]}' for a in Annuncio.objects.all()[:5]) or 'vuota'
    if nome == 'report_statistiche':
        from .views_statistiche import dati_report, testo_report

        return testo_report(dati_report(int(dati.get('giorni') or 7)))
    if nome == 'elenco_pulizie':
        t = _turno(utente)
        righe = [f'id={p.pk}: {p.elemento.nome} · {p.get_stato_display()}' + (' (chiesta da un collega)' if p.richiesta_da_id else '')
                 for p in t.pulizie.select_related('elemento')]
        cose = ', '.join(ElementoPulizia.objects.filter(attivo=True).values_list('nome', flat=True))
        return ('\n'.join(righe) or 'nessuna pulizia assegnata') + f'\nSi possono pulire: {cose}'
    if nome == 'turni_extra':
        return '\n'.join(f'id={e.pk}: {e.data:%d/%m} {e.get_fascia_display()}' + (' (ti sei già offerto)' if e.mia else '')
                         for e in svc.extra_per(_dip(utente))) or 'nessun turno extra'
    raise Errore('Strumento sconosciuto.')


# ---------------------------------------------------------------- azioni: (prepara, esegui)


def _p_fermo(d, u):
    impianti = dict(FermoImpianto.IMPIANTI)
    if d['impianto'] not in impianti or d['causa'] not in FermoImpianto.Causa.values:
        raise Errore('Impianto o causa non validi.')
    m = _macchina(d['macchina_id']) if d.get('macchina_id') else None
    dal = _momento(d.get('giorno'), d.get('dalle'))
    testo = f'Fermo {impianti[d["impianto"]]} · {FermoImpianto.Causa(d["causa"]).label.lower()} dalle {_ora(dal)}'
    if m:
        testo += f' · {m.nome}'
    if d.get('ripartito_alle'):
        if _momento(d.get('giorno'), d['ripartito_alle']) <= dal:
            raise Errore('La ripartenza deve essere dopo l\'inizio del fermo.')
        testo += f' · ripartito alle {d["ripartito_alle"]}'
    if FermoImpianto.objects.filter(impianto=d['impianto'], ripartito_il__isnull=True).exists():
        testo += ' (attenzione: risulta già un fermo in corso)'
    return testo


def _e_fermo(d, u, foto):
    m = _macchina(d['macchina_id']) if d.get('macchina_id') else None
    f = mn.segnala_fermo(u, d['impianto'], d['causa'], m, (d.get('descrizione') or '')[:500], _momento(d.get('giorno'), d.get('dalle')), foto)
    if d.get('ripartito_alle'):
        mn.fai_ripartire(u, f, _momento(d.get('giorno'), d['ripartito_alle']), '')
        return 'Fermo registrato (già ripartito).'
    return 'Fermo segnalato: responsabile, capo turno e manutentori sono avvisati.'


def _fermo(pk):
    f = FermoImpianto.objects.filter(pk=pk, ripartito_il__isnull=True).first()
    if not f:
        raise Errore('Fermo non trovato o già ripartito.')
    return f


def _p_ripartenza(d, u):
    f = _fermo(d['fermo_id'])
    quando = _momento(None, d.get('alle'))
    if quando < f.fermo_dal:
        raise Errore('La ripartenza è prima dell\'inizio del fermo.')
    return f'{f.get_impianto_display()} ripartito alle {_ora(quando)}' + (f' · {d["sistemazione"]}' if d.get('sistemazione') else '')


def _e_ripartenza(d, u, foto):
    f = _fermo(d['fermo_id'])
    mn.fai_ripartire(u, f, _momento(None, d.get('alle')), (d.get('sistemazione') or '')[:500], foto)
    return f'{f.get_impianto_display()} ripartito: tutti avvisati.'


def _p_guasto(d, u):
    m = _macchina(d['macchina_id'])
    if not (d.get('descrizione') or '').strip():
        raise Errore('Scrivi cosa succede.')
    return f'Guasto su {m.nome}' + (' · macchina ferma' if d.get('macchina_ferma') else '') + f': {d["descrizione"][:80]}'


def _e_guasto(d, u, foto):
    mn.segnala(u, _macchina(d['macchina_id']), d['descrizione'][:1000], bool(d.get('macchina_ferma')), foto)
    return 'Guasto segnalato al responsabile della manutenzione.'


def _p_completamento(d, u):
    m = _macchina(d['macchina_id'])
    tipo = _tipi_lavoro().get(d.get('tipo_lavoro') or '', '')
    testo = (d.get('cosa_fatto') or '').strip() or ' · '.join(x for x in (tipo, d.get('pezzo') or '') if x)
    if not testo:
        raise Errore('Scrivi cosa è stato fatto.')
    return f'Manutenzione completata su {m.nome}: {testo[:80]}'


def _e_completamento(d, u, foto):
    tipo = d.get('tipo_lavoro') if d.get('tipo_lavoro') in _tipi_lavoro() else ''
    testo = (d.get('cosa_fatto') or '').strip() or ' · '.join(x for x in (_tipi_lavoro().get(tipo, ''), d.get('pezzo') or '') if x)
    ore = _numero(d.get('ore')) or None
    mn.registra_lavoro(u, _macchina(d['macchina_id']), testo[:1000], [foto], ore, [], tipo, (d.get('pezzo') or '')[:100])
    return 'Manutenzione registrata.'


def _p_programma(d, u):
    if not mn.puo_chiedere_pezzi(u):
        raise Errore('Non hai il permesso.')
    m = _macchina(d['macchina_id'])
    g = _data(d['giorno'])
    ogni = int(d.get('ogni_giorni') or 0)
    return f'Manutenzione programmata su {m.nome}: {d["attivita"][:60]} il {g:%d/%m}' + (f' e poi ogni {ogni} giorni' if ogni else '')


def _e_programma(d, u, foto):
    mn.programma(u, _macchina(d['macchina_id']), d['attivita'][:120], _data(d['giorno']), int(d.get('ogni_giorni') or 0))
    return 'Manutenzione programmata.'


def _p_pulizia_fatta(d, u):
    return f'Pulizia completata: {_pulizia(u, d["pulizia_id"]).elemento.nome}'


def _e_pulizia_fatta(d, u, foto):
    from .pulizie import salva_foto

    p = _pulizia(u, d['pulizia_id'])
    if foto:
        salva_foto(p, foto, 'foto')
    p.nota = (d.get('nota') or '')[:300]
    p.stato, p.fatta_il = Pulizia.Stato.FATTA, timezone.now()
    p.save()
    return f'Pulizia completata: {p.elemento.nome}.'


def _p_aggiuntiva(d, u):
    t = _turno(u)
    el = _elemento(d['cosa'])
    if t.pulizie.filter(elemento=el).exists():
        raise Errore(f'{el.nome} è già nella tua lista: segnala la pulizia assegnata.')
    return f'Pulizia aggiuntiva completata: {el.nome}'


def _e_aggiuntiva(d, u, foto):
    from .pulizie import salva_foto

    t, el = _turno(u), _elemento(d['cosa'])
    p = Pulizia(turno=t, elemento=el, aggiunta_da_operaio=True, nota=(d.get('nota') or '')[:300],
                stato=Pulizia.Stato.FATTA, fatta_il=timezone.now())
    if foto:
        salva_foto(p, foto, 'foto')
    p.save()
    return f'Pulizia aggiuntiva registrata: {el.nome}.'


def _collega_in_turno(u, nome):
    from .assistente import trova_persona
    from .pulizie import in_turno_oggi

    dip = trova_persona(nome, u)
    t = next((c for c in in_turno_oggi(escluso=getattr(u, 'dipendente', None)) if c.dipendente_id == dip.pk), None)
    if not t:
        raise Errore(f'{dip.nome_breve} adesso non è in turno.')
    return t


def _p_richiesta(d, u):
    t, el = _collega_in_turno(u, d['collega']), _elemento(d['cosa'])
    if t.pulizie.filter(elemento=el).exists():
        raise Errore(f'{el.nome} è già nella lista di {t.dipendente.nome_breve}.')
    return f'Chiedi a {t.dipendente.nome_breve} di pulire {el.nome}'


def _e_richiesta(d, u, foto):
    from .pulizie import richiedi_pulizia

    t, el = _collega_in_turno(u, d['collega']), _elemento(d['cosa'])
    try:
        richiedi_pulizia(u, t, el, d.get('nota') or '')
    except ValueError as e:
        raise Errore(str(e))
    return f'Richiesta inviata a {t.dipendente.nome_breve}.'


def _p_impedimento(d, u):
    p = _pulizia(u, d['pulizia_id'])
    if d.get('motivo') not in Pulizia.MOTIVI_IMPEDIMENTO:
        raise Errore('Scegli il motivo.')
    return f'Pulizia non eseguibile: {p.elemento.nome} · {d["motivo"]}'


def _e_impedimento(d, u, foto):
    from .pulizie import salva_foto

    p = _pulizia(u, d['pulizia_id'])
    salva_foto(p, foto, 'foto')
    nota = (d.get('nota') or '').strip()
    p.nota = (d['motivo'] + (f': {nota}' if nota else ''))[:300]
    p.stato, p.fatta_il = Pulizia.Stato.IMPEDITA, timezone.now()
    p.save()
    mn.avvisa(mn.capiturno_oggi(), u, f'🧹 Pulizia non eseguibile · {p.turno.dipendente.nome_breve}',
              f'{p.elemento.nome}: {p.nota}', reverse('turni:capoturno'))
    return 'Impedimento segnalato al capo turno.'


def _righe_produzione(d):
    prodotti = {p.codice.upper(): p for p in ProdottoProduzione.objects.filter(attivo=True)}
    righe = []
    for r in d.get('righe') or []:
        p = prodotti.get(str(r.get('codice', '')).strip().upper())
        if not p:
            raise Errore(f'Codice sconosciuto: {r.get("codice")}. Codici: {", ".join(prodotti)}')
        righe.append((p, _numero(r.get('tonnellate')).quantize(Decimal('0.01'))))
    if not righe:
        raise Errore('Servono le tonnellate di almeno un prodotto.')
    return righe


def _p_produzione(d, u):
    g = _data(d['giorno'])
    if d.get('fascia') not in ('1T', '2T', 'N'):
        raise Errore('Indica il turno.')
    righe = _righe_produzione(d)
    return f'Produzione {g:%d/%m} {d["fascia"]}: ' + ', '.join(f'{p.codice} {t} t' for p, t in righe)


def _e_produzione(d, u, foto):
    from .views_produzione import confronto, medie

    g = _data(d['giorno'])
    t, _ = ProduzioneTurno.objects.get_or_create(data=g, fascia=d['fascia'], defaults={'inserita_da': u})
    t.inserita_da, t.inserita_il = u, timezone.now()
    if d.get('note'):
        t.note = d['note'][:500]
    if foto:
        t.foto.save('display.jpg', foto, save=False)
    t.save()
    for p, v in _righe_produzione(d):
        RigaProduzione.objects.update_or_create(produzione=t, prodotto=p, defaults={'tonnellate': v})
    alti = [x for x in confronto(t, medie(g - timedelta(days=1))) if x['alto']]
    if alti:
        testo = ', '.join(f"{x['r'].prodotto.nome} {x['perc']:.1f}% (media {x['media']:.1f}%)" for x in alti)
        mn.avvisa(mn.responsabili(), u, f'📊 Scarto alto · {t}', testo, reverse('turni:produzione_turno', args=[t.pk]))
    return 'Produzione salvata.' + (' Attenzione: scarto alto, responsabile avvisato.' if alti else '')


def _analisi(d):
    if d.get('campione') not in AnalisiProdotto.Campione.values:
        raise Errore('Indica il campione.')
    valori = {c: _numero(d.get(c)) for c, _, _ in INQUINANTI}
    if all(v is None for v in valori.values()):
        raise Errore('Serve almeno un valore.')
    num = _numero(d.get('numero'))
    return AnalisiProdotto(data=_data(d['giorno']), fascia=d.get('fascia') or '', campione=d['campione'],
                           peso_kg=_numero(d.get('peso_kg')), numero=int(num) if num is not None else None,
                           note=(d.get('note') or '')[:500], **valori)


def _p_analisi(d, u):
    a = _analisi(d)
    parti = [f'{v["nome"]} {v["g"]} g' + (f' ({v["gt"]:.0f} g/t)' if v['gt'] is not None else '') for v in a.valori()]
    fuori = [v['nome'] for v in a.fuori_limite]
    return (f'Analisi {a.get_campione_display()} {a.data:%d/%m}' + (f' · {a.peso_kg} kg' if a.peso_kg else '') + ': '
            + ', '.join(parti) + (f' · FUORI LIMITE: {", ".join(fuori)}' if fuori else ''))


def _e_analisi(d, u, foto):
    a = _analisi(d)
    a.inserita_da = u
    if foto:
        a.foto.save('analisi.jpg', foto, save=False)
    a.save()
    if a.fuori_limite:
        testo = ', '.join(f"{v['nome']} {v['gt']:.0f} g/t (limite {v['limite']})" for v in a.fuori_limite)
        mn.avvisa(mn.responsabili(), u, f'🧪 Fuori limite · {a}', testo, reverse('turni:analisi', args=[a.pk]))
    return 'Analisi salvata.'


def _chat(u, nome):
    from .views_messaggi import chat_visibili

    chat = [c for c in chat_visibili(u) if (nome or '').lower() in c.nome.lower()]
    if len(chat) != 1:
        raise Errore('Quale chat? ' + ', '.join(c.nome for c in chat_visibili(u)))
    return chat[0]


def _p_messaggio(d, u):
    if not (d.get('testo') or '').strip():
        raise Errore('Scrivi il messaggio.')
    return f'Messaggio in "{_chat(u, d["chat"]).nome}": {d["testo"][:120]}'


def _e_messaggio(d, u, foto):
    from . import push
    from .models import MessaggioChat
    from .views_messaggi import _url_chat, destinatari, nome_di

    c = _chat(u, d['chat'])
    m = MessaggioChat.objects.create(chat=c, autore=u, testo=d['testo'][:1000])
    push.invia(destinatari(u, c), f'{c.nome} · {nome_di(u)}', m.testo, _url_chat(c))
    return f'Messaggio inviato in {c.nome}.'


def _p_annuncio(d, u):
    if not svc.e_responsabile(u):
        raise Errore('Non hai il permesso.')
    return ('Avviso importante' if d.get('importante') else 'Avviso') + f' in bacheca: {d["testo"][:120]}'


def _e_annuncio(d, u, foto):
    from . import push
    from .models import Annuncio
    from .views_messaggi import destinatari

    a = Annuncio.objects.create(testo=d['testo'][:2000], importante=bool(d.get('importante')), autore=u)
    push.invia(destinatari(u), 'Avviso importante' if a.importante else 'Bacheca Sarco', a.testo, reverse('turni:messaggi') + '?vista=bacheca')
    return 'Avviso pubblicato in bacheca.'


def _extra(u, pk):
    e = TurnoExtra.objects.filter(pk=pk, chiusa=False).first()
    if not e:
        raise Errore('Turno extra non trovato.')
    return e


def _p_disponibilita(d, u):
    e = _extra(u, d['extra_id'])
    return ('Ti offri' if d['disponibile'] else 'Ritiri la disponibilità') + f' per il {e.data:%d/%m} {e.get_fascia_display()}'


def _e_disponibilita(d, u, foto):
    e, dip = _extra(u, d['extra_id']), _dip(u)
    (svc.offri if d['disponibile'] else svc.ritira)(e, dip)
    return 'Fatto: l\'ufficio ti farà sapere.' if d['disponibile'] else 'Disponibilità ritirata.'


def _cambio(u, pk):
    c = CambioTurno.objects.filter(pk=pk, collega=_dip(u), stato=CambioTurno.Stato.ATTESA_COLLEGA).first()
    if not c:
        raise Errore('Richiesta di cambio non trovata.')
    return c


def _p_risposta_cambio(d, u):
    c = _cambio(u, d['cambio_id'])
    return ('Accetti' if d['accetta'] else 'Rifiuti') + f' il cambio chiesto da {c.richiedente.nome_breve} per il {c.giorno1:%d/%m}'


def _e_risposta_cambio(d, u, foto):
    svc.risposta_collega(_cambio(u, d['cambio_id']), d['accetta'])
    return 'Cambio accettato: ora deve approvarlo l\'ufficio.' if d['accetta'] else 'Cambio rifiutato.'


def _p_presa_visione(d, u):
    n = ModificaTurno.objects.filter(dipendente=_dip(u), vista_il__isnull=True).count()
    if not n:
        raise Errore('Non ci sono turni cambiati da vedere.')
    return f'Presa visione di {n} turn{"o cambiato" if n == 1 else "i cambiati"}'


def _e_presa_visione(d, u, foto):
    ModificaTurno.objects.filter(dipendente=_dip(u), vista_il__isnull=True).update(vista_il=timezone.now())
    return 'Presa visione registrata.'


AZIONI = {
    'proponi_fermo': (_p_fermo, _e_fermo),
    'proponi_ripartenza': (_p_ripartenza, _e_ripartenza),
    'proponi_guasto': (_p_guasto, _e_guasto),
    'proponi_completamento_manutenzione': (_p_completamento, _e_completamento),
    'proponi_programma_manutenzione': (_p_programma, _e_programma),
    'proponi_pulizia_fatta': (_p_pulizia_fatta, _e_pulizia_fatta),
    'proponi_pulizia_aggiuntiva': (_p_aggiuntiva, _e_aggiuntiva),
    'proponi_richiesta_pulizia': (_p_richiesta, _e_richiesta),
    'proponi_impedimento_pulizia': (_p_impedimento, _e_impedimento),
    'proponi_produzione': (_p_produzione, _e_produzione),
    'proponi_analisi': (_p_analisi, _e_analisi),
    'proponi_messaggio_chat': (_p_messaggio, _e_messaggio),
    'proponi_annuncio': (_p_annuncio, _e_annuncio),
    'proponi_disponibilita': (_p_disponibilita, _e_disponibilita),
    'proponi_risposta_cambio': (_p_risposta_cambio, _e_risposta_cambio),
    'proponi_presa_visione': (_p_presa_visione, _e_presa_visione),
}


def prepara(nome, dati, utente, ha_foto=False):
    if nome in SERVE_FOTO and not ha_foto:
        raise Errore('Serve una foto: chiedi di premere 📷 accanto al messaggio e di allegarla.')
    return AZIONI[nome][0](dati, utente)


def esegui(nome, dati, utente, foto=None):
    if nome in SERVE_FOTO and not foto:
        raise Errore('Manca la foto.')
    AZIONI[nome][0](dati, utente)  # ricontrolla: i dati possono essere cambiati
    return AZIONI[nome][1](dati, utente, foto)
