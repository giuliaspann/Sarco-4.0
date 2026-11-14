"""Il quadrato centrale della barra (stile Instagram): tutte le funzioni dell'app, divise per sezione,
e la home dell'ufficio con le 4 funzioni più usate. Ognuno vede solo quello che può usare."""

import re
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

# icone a linea (stesso tratto dei riquadri di Oggi)
ICONE = {
    'comunicazioni': '<path d="M4 10v4h3l7 4V6L7 10H4z"/><path d="M17.5 9a4 4 0 010 6"/>',
    'scadenze': '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2.5 2M5 4l3 2M19 4l-3 2"/>',
    'documenti': '<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 13h6M9 17h6"/>',
    'riunione': '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/><circle cx="9" cy="15" r="1.5"/><circle cx="15" cy="15" r="1.5"/>',
    'pulizia': '<path d="M14 3l-4 9M6 12h12l-1.5 9h-9z"/>',
    'manutenzione': '<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.5-.5-.5-2.5z"/>',
    'produzione': '<path d="M12 3v18M5 7h14M5 7l-3 7a3 3 0 0 0 6 0zM19 7l-3 7a3 3 0 0 0 6 0z"/>',
    'analisi': '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/>',
    'fermo': '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    'riparti': '<path d="M8 5l11 7-11 7z"/>',
    'verifica': '<path d="M9 4h6v3H9zM7 5H5v16h14V5h-2M8.5 13.5l2.5 2.5 4.5-5"/>',
    'piazzale': '<path d="M6 21V4h7a4 4 0 0 1 0 8H6"/>',
    'calendario': '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
    'tutti': '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M3 14h18M9 4v16"/>',
    'squadra': '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.5-4 3-6 6.5-6s6 2 6.5 6"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14c3 0 5 1.6 5.5 5"/>',
    'cambio': '<path d="M4 8h13l-3-3M20 16H7l3 3"/>',
    'orologio': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'richieste': '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    'macchine': '<rect x="3" y="7" width="18" height="11" rx="2"/><circle cx="8" cy="18" r="2"/><circle cx="16" cy="18" r="2"/><path d="M7 7V4h6v3"/>',
    'ricambi': '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    'ordini': '<path d="M3 4h2l2.5 11h11L21 7H6"/><circle cx="9" cy="19" r="1.5"/><circle cx="17" cy="19" r="1.5"/>',
    'programmate': '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 15l2 2 4-4"/>',
    'avvisi': '<path d="M4 10v4h3l5 4V6L7 10zM16 9a4 4 0 0 1 0 6"/>',
    'statistiche': '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
    'report': '<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 13h6M9 17h6"/>',
    'archivio': '<rect x="3" y="4" width="18" height="5" rx="1"/><path d="M5 9v11h14V9M10 13h4"/>',
    'foto': '<rect x="3" y="5" width="18" height="15" rx="2"/><circle cx="9" cy="11" r="2"/><path d="M21 17l-5-5-9 8"/>',
    'carica': '<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>',
    'dipendenti': '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4.5 4.2-6.5 8-6.5s7 2 8 6.5"/>',
    'extra': '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
    'zone': '<path d="M3 7l6-3 6 3 6-3v13l-6 3-6-3-6 3z"/><path d="M9 4v13M15 7v13"/>',
}


def voce(nome, url, icona, badge=0):
    return {'nome': nome, 'url': url, 'icona': ICONE[icona], 'badge': badge}


def home_ufficio(request):
    """Home dell'ufficio (Giulia, 11/11): 4 tasti per le cose di ogni giorno, poi Persone e Azienda.
    Le funzioni scelte guardando le piattaforme HR più usate (approvazioni, turni, comunicazioni, anagrafica,
    presenze, scadenze, documenti)."""
    from .context import navigazione
    from .models import FermoImpianto
    from .views_calendario import eventi_prossimi
    from .views_hr import scadenze_vicine
    from .views_riunioni import puo_programmare_riunione

    u = request.user
    nav = navigazione(request)
    r = reverse
    principali = []
    if nav.get('nav_responsabile'):
        principali.append(voce('Richieste', r('turni:ufficio_richieste'), 'richieste', nav.get('nav_da_approvare', 0)))
    if nav.get('nav_responsabile') or u.is_staff:
        principali.append(voce('Turni', r('turni:ufficio_turni'), 'carica'))
    if puo_programmare_riunione(u):
        principali.append(voce('Riunioni', r('turni:riunioni'), 'riunione'))
    persone = []
    if u.is_staff:
        persone.append({**voce('Gestione accessi', r('turni:accessi'), 'dipendenti'), 'sotto': 'Attiva o disattiva un accesso'})
        persone.append({**voce('Anagrafica', r('turni:anagrafica'), 'report'), 'sotto': 'Dati, presenze, assenze e indici'})
        persone.append({**voce('Scadenze', r('turni:scadenze'), 'scadenze', len(scadenze_vicine())),
                        'sotto': 'Visite mediche, corsi sicurezza, patentini'})
        persone.append({**voce('Documenti', r('turni:documenti_ufficio'), 'documenti'), 'sotto': 'Buste paga, regolamenti, presa visione'})
    azienda = [{**voce('Archivio', r('turni:archivio'), 'archivio'), 'sotto': 'Gli stessi tasti del Capo Turno', 'blu': True}]
    dip = getattr(u, 'dipendente', None)
    nome = dip.nome_breve if dip else (u.first_name or u.username).split()[0].capitalize()
    return render(request, 'turni/home_ufficio.html', {
        'principali': principali[:4], 'persone': persone, 'azienda': azienda,
        'nome': nome,
        'oggi_data': timezone.localdate(),
        'fermi_aperti': FermoImpianto.objects.filter(ripartito_il__isnull=True).order_by('fermo_dal'),
        'eventi_settimana': eventi_prossimi(u, 7),
    })


@login_required
def profilo(request):
    """Il tasto profilo della barra: per chi ha turni è l'Area personale; per l'ufficio una pagina sua
    (nome, ruolo, cambio password, esci) invece della pagina di amministrazione."""
    from django.shortcuts import redirect

    from .models import RuoloApp
    from .richieste import e_responsabile

    u = request.user
    dip = getattr(u, 'dipendente', None)
    # un dipendente collegato non basta: direzione/HR/amministrazione sono "ufficio" anche se hanno
    # un dipendente collegato (serve per altri motivi, es. HR) — solo chi lavora davvero a turni fisici
    # (ruolo_app OPERAIO, come già distingue ufficio_dipendenti.html) va sulla sua Area personale
    if dip and dip.ruolo_app == RuoloApp.OPERAIO:
        return redirect('turni:miei_turni')
    nome = (dip.nome_breve if dip else '') or (u.get_full_name() or u.username).strip()
    ruoli = [r for r, si in (('Ufficio', u.is_staff), ('Responsabile', e_responsabile(u))) if si]
    return render(request, 'turni/profilo_ufficio.html', {
        'nome': nome.title() if nome.islower() else nome,
        'iniziali': ''.join(p[0] for p in nome.split()[:2]).upper() or '?',
        'ruoli': ' · '.join(ruoli),
    })


# ---------------------------------------------------------------- centro notifiche (come Instagram, Giulia 10/11)
#
# Una riga per ogni cosa: gli avvisi ricevuti (modello Notifica) e le cose che aspettano la persona adesso
# (cambi turno, pulizie da verificare o convalidare, manutenzioni, pezzi, turni cambiati...). Nessuna area "Da fare":
# ogni cosa ha la sua riga, e quelle che chiedono una risposta hanno Conferma / Rifiuta.

TIPI_CON_RISPOSTA = ('cambio', 'cambio_ufficio', 'manutenzione', 'pulizia_ct', 'pulizia_rp', 'riunione', 'straordinaria')


def _tondino(utente):
    """Foto del dipendente che ha generato la notifica, oppure le sue iniziali (l'ufficio: la sua iniziale)."""
    dip = getattr(utente, 'dipendente', None) if utente else None
    from .foto_profilo import foto_url

    if foto_url(utente):
        return {'foto': foto_url(utente)}
    if dip:
        parole = dip.nome_breve.replace("'", ' ').replace('’', ' ').split()
        return {'iniziali': (parole[0][:1] + (parole[-1][:1] if len(parole) > 1 else '')).upper()}
    if utente:
        return {'iniziali': (utente.get_full_name() or utente.username)[:1].upper()}
    return {'iniziali': 'S'}


def _quando(dt):
    """Come Instagram: 34 min, 9 h, 3 g, poi la data."""
    secondi = (timezone.now() - dt).total_seconds()
    if secondi < 3600:
        return f'{max(1, int(secondi // 60))} min'
    if secondi < 86400:
        return f'{int(secondi // 3600)} h'
    if secondi < 7 * 86400:
        return f'{int(secondi // 86400)} g'
    return timezone.localtime(dt).strftime('%d/%m')


def _sezione(dt):
    giorni = (timezone.localdate() - timezone.localtime(dt).date()).days
    if giorni <= 0:
        return 'Oggi'
    if giorni == 1:
        return 'Ieri'
    if giorni < 7:
        return 'Ultimi 7 giorni'
    if giorni < 30:
        return 'Ultimi 30 giorni'
    return 'Meno recenti'


SEZIONI = ['Oggi', 'Ieri', 'Ultimi 7 giorni', 'Ultimi 30 giorni', 'Meno recenti']
ESITI = {'confermata': 'Hai confermato', 'rifiutata': 'Hai rifiutato'}


def _oggetto(tipo, oggetto_id):
    from .models import CambioTurno, Intervento, Pulizia

    if tipo in ('cambio', 'cambio_ufficio'):
        return CambioTurno.objects.filter(pk=oggetto_id).select_related('richiedente', 'collega').first()
    if tipo == 'manutenzione':
        return Intervento.objects.filter(pk=oggetto_id).select_related('macchina').first()
    if tipo in ('pulizia_ct', 'pulizia_rp', 'pulizia'):
        return Pulizia.objects.filter(pk=oggetto_id).select_related('turno__dipendente', 'elemento').first()
    if tipo == 'riunione':
        from .models import InvitoRiunione
        return InvitoRiunione.objects.filter(pk=oggetto_id).select_related('riunione__creata_da', 'dipendente').first()
    if tipo == 'straordinaria':
        from .models import Straordinaria
        return Straordinaria.objects.filter(pk=oggetto_id).select_related('chiesta_da').first()
    return None


def puo_rispondere(tipo, ogg, utente):
    """Questa persona può rispondere adesso (Conferma / Rifiuta) a questa richiesta?"""
    from .models import CambioTurno, ElementoPulizia, Intervento, Pulizia
    from .pulizie import e_resp_piazzale
    from .richieste import e_responsabile
    from .views import fasce_del_capo

    if ogg is None:
        return False
    dip = getattr(utente, 'dipendente', None)
    if tipo == 'riunione':
        from .views_riunioni import puo_rispondere as puo_rispondere_riunione
        return puo_rispondere_riunione(ogg, utente)
    if tipo == 'straordinaria':
        return bool(dip and dip.resp_piazzale and ogg.stato == ogg.Stato.ATTESA)
    if tipo == 'cambio':
        return bool(dip and ogg.collega_id == dip.pk and ogg.stato == CambioTurno.Stato.ATTESA_COLLEGA and not ogg.scaduto)
    if tipo == 'cambio_ufficio':
        return e_responsabile(utente) and ogg.stato == CambioTurno.Stato.ATTESA_UFFICIO
    if tipo == 'manutenzione':
        return bool(dip and ogg.assegnata_a_id == dip.pk and ogg.stato == Intervento.Stato.SEGNALATA)
    if tipo == 'pulizia_ct':
        if ogg.stato != Pulizia.Stato.FATTA or ogg.ok_capoturno_il or ogg.turno.dipendente.utente_id == utente.pk:
            return False
        if ogg.elemento_id and ogg.elemento.convalida == ElementoPulizia.Convalida.PIAZZALE:
            return False
        if not ogg.elemento_id and ogg.turno.capoturno:
            return False  # straordinaria fatta dal Capo Turno: la convalida direttamente il responsabile piazzale
        fasce = fasce_del_capo(utente, ogg.turno.data)
        return bool(fasce and ogg.turno.fascia in fasce)
    if tipo == 'pulizia_rp':
        if not e_resp_piazzale(utente) or ogg.stato != Pulizia.Stato.FATTA:
            return False
        from .piano_pulizie import va_al_rp
        return va_al_rp(ogg)
    return False


def in_attesa(request):
    """Le cose che aspettano la persona adesso, una riga ciascuna (al posto dell'area "Da fare")."""
    from .manutenzione import e_resp, puo_approvare
    from .models import CambioTurno, ElementoPulizia, Intervento, OrdineRicambio, Pulizia
    from .pulizie import da_convalidare_piazzale, e_resp_piazzale
    from .richieste import e_responsabile, extra_per
    from .views import e_capoturno, fasce_del_capo

    u = request.user
    dip = getattr(u, 'dipendente', None)
    r = reverse
    righe = []

    def riga(tipo, oggetto_id, titolo, testo, url, quando, mittente=None):
        righe.append({'tipo': tipo, 'oggetto_id': oggetto_id, 'titolo': titolo, 'testo': testo, 'url': url,
                      'quando_dt': quando or timezone.now(), 'mittente': mittente})

    if dip:
        for c in CambioTurno.objects.filter(collega=dip, stato=CambioTurno.Stato.ATTESA_COLLEGA).select_related('richiedente__utente'):
            if not c.scaduto:
                riga('cambio', c.pk, f'{c.richiedente.nome_breve} ti chiede un cambio turno',
                     ' e '.join(f'{g:%a %d/%m}' for g in c.giorni), r('turni:richieste'), c.creato_il, c.richiedente.utente)
        for m in dip.modifiche_turno.filter(vista_il__isnull=True):
            riga('', None, 'Il tuo turno è cambiato', f'{m.data:%a %d/%m}: {m.prima} → {m.dopo}', r('turni:messaggi'), m.creata_il)
        from .models import InvitoRiunione
        from .views_riunioni import quando as quando_riunione
        for inv in InvitoRiunione.objects.filter(dipendente=dip, risposta='', riunione__annullata=False,
                                                 riunione__fine__gt=timezone.now()).select_related('riunione__creata_da'):
            rr = inv.riunione
            riga('riunione', inv.pk, f'Riunione: {rr.titolo}', f'{quando_riunione(rr)} · {rr.luogo}',
                 r('turni:riunione', args=[rr.pk]), rr.creata_il, rr.creata_da)
        from .models import RuoloApp

        if dip.ruolo_app == RuoloApp.OPERAIO:  # i turni extra sono per chi lavora davvero a turni fisici
            for e in extra_per(dip):
                if not e.mia:
                    riga('', None, 'Cercasi volontari', f'{e.data:%a %d/%m} · {e.descrizione_fascia}', r('turni:miei_turni'), e.creata_il)
        for i in Intervento.objects.filter(assegnata_a=dip, stato__in=[Intervento.Stato.SEGNALATA, Intervento.Stato.ASSEGNATA]
                                           ).select_related('macchina', 'segnalata_da__dipendente'):
            riga('manutenzione', i.pk, f'Manutenzione da eseguire · {i.macchina.nome}', i.descrizione,
                 r('turni:intervento', args=[i.pk]), i.segnalata_il, i.segnalata_da)
    if dip:
        from .views_hr import da_leggere
        for d in da_leggere(dip):
            riga('', None, f'Documento da leggere: {d.titolo}', d.get_tipo_display(), r('turni:documenti'), d.caricato_il, d.caricato_da)
    if u.is_staff:
        from .views_hr import scadenze_vicine
        for s in scadenze_vicine():
            quando = 'scaduta' if s.stato == 'scaduta' else ('scade oggi' if s.giorni == 0 else f'scade tra {s.giorni} g')
            riga('', None, f'{s.get_tipo_display()} · {s.dipendente.nome_breve}', f'{quando} ({s.scade_il:%d/%m/%Y})',
                 r('turni:scadenze'), timezone.now(), s.dipendente.utente)  # sempre in cima, finché non si rinnova
    if e_responsabile(u):
        for c in CambioTurno.objects.filter(stato=CambioTurno.Stato.ATTESA_UFFICIO).select_related('richiedente__utente', 'collega'):
            riga('cambio_ufficio', c.pk, f'Cambio turno da approvare: {c.richiedente.nome_breve} ↔ {c.collega.nome_breve}',
                 ' e '.join(f'{g:%a %d/%m}' for g in c.giorni), r('turni:ufficio_richieste'),
                 c.risposta_collega_il or c.creato_il, c.richiedente.utente)
    if puo_approvare(u):
        for i in Intervento.objects.filter(stato=Intervento.Stato.SEGNALATA, assegnata_a__isnull=True
                                           ).select_related('macchina', 'segnalata_da__dipendente'):
            riga('', None, f'Guasto da assegnare · {i.macchina.nome}', i.descrizione, r('turni:intervento', args=[i.pk]),
                 i.segnalata_il, i.segnalata_da)
    if e_resp(u):
        for o in OrdineRicambio.objects.filter(stato=OrdineRicambio.Stato.RICHIESTO):
            riga('', None, f'Pezzo da approvare · n. {o.numero}', f'{o.nome} × {o.quantita}', r('turni:ordini'),
                 o.richiesto_il, getattr(o, 'richiesto_da', None))
    if dip and dip.acquisti:
        for o in OrdineRicambio.objects.filter(stato=OrdineRicambio.Stato.APPROVATO):
            riga('', None, f'Pezzo da ordinare · n. {o.numero}', f'{o.nome} × {o.quantita}', r('turni:ordini'),
                 o.richiesto_il, getattr(o, 'richiesto_da', None))
    # pulizie fatte che aspettano l'ok del Capo Turno (solo il suo turno; l'ufficio vede tutto)
    oggi = timezone.localdate()
    if e_capoturno(u, oggi):
        for giorno in (oggi, oggi - timedelta(days=1)):
            fasce = fasce_del_capo(u, giorno)
            if fasce == set():
                continue
            q = Pulizia.objects.filter(turno__data=giorno, stato=Pulizia.Stato.FATTA, ok_capoturno_il__isnull=True).exclude(
                elemento__convalida=ElementoPulizia.Convalida.PIAZZALE).exclude(elemento__isnull=True, turno__capoturno=True
                                                                                ).select_related('turno__dipendente__utente', 'elemento')
            if fasce is not None:
                q = q.filter(turno__fascia__in=fasce)
            for p in q:
                if p.turno.dipendente.utente_id != u.pk:
                    riga('pulizia_ct', p.pk, f'{p.turno.dipendente.nome_breve} ha completato una pulizia', p.titolo,
                         r('turni:capoturno') + f'?giorno={giorno.isoformat()}', p.fatta_il, p.turno.dipendente.utente)
    if e_resp_piazzale(u):
        for p in da_convalidare_piazzale().select_related('turno__dipendente__utente'):
            riga('pulizia_rp', p.pk, f'Pulizia da convalidare · {p.turno.dipendente.nome_breve}', p.titolo,
                 r('turni:pulizie_piazzale'), p.ok_capoturno_il or p.fatta_il, p.turno.dipendente.utente)
    return righe


def _tasto_avviso(n, utente):
    """Avviso automatico delle pulizie (Giulia, 12/11/2026): il tasto giusto finché la pulizia non è fatta."""
    from .models import Pulizia
    from .piano_pulizie import nome_corto

    from .views_pulizie_piano import _e_capo

    p = Pulizia.objects.filter(pk=n.oggetto_id).select_related('elemento', 'turno').first() if n.oggetto_id else None
    if p is None or p.stato != Pulizia.Stato.DA_FARE:
        return None
    e = p.elemento
    if e and e.con_avvio and not _e_capo(utente, p):
        return {'testo': 'Apri', 'pk': p.pk}  # il manutentore riceve l'avviso, ma i tasti delle ottiche sono del Capo Turno
    if e and e.con_avvio and not p.iniziata_il:
        return {'testo': f'Pulizia {nome_corto(e)} iniziata', 'azione': 'iniziata', 'pk': p.pk}
    if e and e.con_avvio:
        return {'testo': f'Pulizia {nome_corto(e)} conclusa', 'pk': p.pk}
    if e and e.avviso == 'ENTRO':
        return {'testo': 'Rispondi', 'pk': p.pk}
    return {'testo': 'Apri', 'pk': p.pk}


def _righe_notifiche(request):
    """Tutte le righe del centro notifiche, dalla più recente: avvisi e cose in attesa, senza doppioni."""
    from .models import Notifica

    u = request.user
    attese = in_attesa(request)
    chiavi_attese = {(a['tipo'], a['oggetto_id']) for a in attese if a['tipo']}
    righe, viste = [], set()
    for n in Notifica.objects.filter(utente=u).select_related('mittente__dipendente')[:80]:
        chiave = (n.tipo, n.oggetto_id)
        if n.tipo in TIPI_CON_RISPOSTA and chiave in viste:
            continue  # una sola riga per richiesta
        ogg = _oggetto(n.tipo, n.oggetto_id) if n.tipo in TIPI_CON_RISPOSTA else None
        azioni = n.tipo in TIPI_CON_RISPOSTA and puo_rispondere(n.tipo, ogg, u)
        esito = ''
        if n.tipo == 'pulizia':
            esito = 'Accettata in automatico'
        elif n.tipo in TIPI_CON_RISPOSTA and not azioni:
            esito = ESITI.get(n.esito) or (ogg.get_stato_display() if ogg is not None and hasattr(ogg, 'get_stato_display') else '')
        viste.add(chiave)
        righe.append({'tipo': n.tipo, 'oggetto_id': n.oggetto_id, 'titolo': re.sub(r'^[^\w(]+', '', n.titolo),
                      'testo': n.testo, 'url': n.url, 'quando_dt': n.creata_il, 'mittente': n.mittente,
                      'azioni': azioni, 'esito': esito, 'nuova': n.letta_il is None,
                      'tasto': _tasto_avviso(n, u) if n.tipo == 'avviso_pulizia' else None})
    for a in attese:
        if a['tipo'] and (a['tipo'], a['oggetto_id']) in viste:
            continue  # c'è già la notifica di questa richiesta
        ogg = _oggetto(a['tipo'], a['oggetto_id']) if a['tipo'] in TIPI_CON_RISPOSTA else None
        a.update(azioni=a['tipo'] in TIPI_CON_RISPOSTA and puo_rispondere(a['tipo'], ogg, u), esito='', nuova=True)
        righe.append(a)
    righe.sort(key=lambda x: x['quando_dt'], reverse=True)
    del chiavi_attese
    return righe


def conta_notifiche(request, nav=None):
    """Il numero sulla campanella: avvisi non letti + cose che aspettano una risposta."""
    return sum(1 for r in _righe_notifiche(request) if r['nuova'] or r.get('azioni'))


@login_required
def notifiche(request):
    """Il centro notifiche (la campanella in alto a destra), come Instagram: una riga per ogni cosa,
    divise per Oggi / Ieri / Ultimi 7 giorni / Ultimi 30 giorni, con il tondino di chi l'ha generata
    e Conferma / Rifiuta per quello che aspetta una risposta."""
    from .models import Notifica

    gruppi = {}
    for r in _righe_notifiche(request):
        r.update(tondino=_tondino(r['mittente']), quando=_quando(r['quando_dt']))
        gruppi.setdefault(_sezione(r['quando_dt']), []).append(r)
    Notifica.objects.filter(utente=request.user, letta_il__isnull=True).update(letta_il=timezone.now())
    return render(request, 'turni/notifiche.html', {'sezioni': [(s, gruppi[s]) for s in SEZIONI if s in gruppi]})


@login_required
def notifica_scelta(request, tipo, oggetto_id, scelta):
    """Conferma / Rifiuta dal centro notifiche: prima il riepilogo di cosa cambierà (o non cambierà), poi la convalida."""
    from django.contrib import messages
    from django.http import Http404
    from django.shortcuts import redirect

    from . import manutenzione as mn
    from . import richieste as svc
    from .models import ElementoPulizia, Notifica, Pulizia
    from .pulizie import resp_piazzale
    from .views_richieste import _righe_cambio

    if scelta not in ('conferma', 'rifiuta') or tipo not in TIPI_CON_RISPOSTA:
        raise Http404
    ogg = _oggetto(tipo, oggetto_id)
    if not puo_rispondere(tipo, ogg, request.user):
        messages.info(request, 'Questa richiesta non aspetta più una tua risposta.')
        return redirect('turni:notifiche')
    conferma = scelta == 'conferma'
    if tipo == 'straordinaria' and conferma:
        return redirect('turni:richiesta_rp', ogg.pk)  # il RP sceglie a chi assegnarla (Giulia, 13/11/2026)
    if request.method == 'POST':
        nota = (request.POST.get('nota') or '').strip()[:300]
        try:
            if tipo == 'riunione':
                from .views_riunioni import rispondi
                rispondi(ogg, conferma)
                fatto = f'Partecipazione confermata: {ogg.riunione.titolo}.' if conferma else 'Hai detto che non partecipi alla riunione.'
            elif tipo == 'straordinaria':
                from .pulizie import rifiuta_richiesta

                rifiuta_richiesta(request.user, ogg, nota)
                fatto = 'Richiesta non approvata.'
            elif tipo == 'cambio':
                svc.risposta_collega(ogg, conferma)
                fatto = "Cambio confermato: ora decide l'ufficio." if conferma else 'Cambio rifiutato.'
            elif tipo == 'cambio_ufficio':
                svc.decisione_ufficio_cambio(ogg, request.user, conferma, nota)
                fatto = 'Cambio approvato: i turni sono stati scambiati.' if conferma else 'Cambio non approvato.'
            elif tipo == 'manutenzione':
                if conferma:
                    mn.accetta_richiesta(request.user, ogg)
                    fatto = f'Manutenzione presa in carico: {ogg.macchina.nome}.'
                else:
                    mn.rifiuta_richiesta(request.user, ogg, nota)
                    fatto = 'Richiesta rifiutata: torna al responsabile manutenzione.'
            elif tipo == 'pulizia_ct':
                if conferma and ogg.elemento_id and ogg.elemento.convalida == ElementoPulizia.Convalida.CT_RP:
                    ogg.ok_capoturno_da, ogg.ok_capoturno_il, ogg.nota_verifica = request.user, timezone.now(), nota
                    ogg.save()
                    mn.avvisa(resp_piazzale(), request.user, f'{ogg.titolo} · {ogg.turno.dipendente.nome_breve}',
                              'Ok del Capo Turno: da convalidare', reverse('turni:pulizie_piazzale'), tipo='pulizia_rp', oggetto_id=ogg.pk)
                    fatto = f'{ogg.titolo}: ok, inviata al responsabile piazzale.'
                else:
                    ogg.stato = Pulizia.Stato.VERIFICATA if conferma else Pulizia.Stato.SEGNALATA
                    ogg.verificata_da, ogg.verificata_il, ogg.nota_verifica = request.user, timezone.now(), nota
                    ogg.save()
                    fatto = f'{ogg.titolo}: ' + ('approvata.' if conferma else 'da rifare.')
            else:  # pulizia_rp
                ogg.stato = Pulizia.Stato.VERIFICATA if conferma else Pulizia.Stato.SEGNALATA
                ogg.verificata_da, ogg.verificata_il, ogg.nota_verifica = request.user, timezone.now(), nota
                ogg.save()
                fatto = f'{ogg.titolo}: ' + ('convalidata.' if conferma else 'da rifare.')
        except (svc.RichiestaNonValida, ValueError) as e:
            messages.error(request, str(e))
        else:
            Notifica.objects.filter(utente=request.user, tipo=tipo, oggetto_id=oggetto_id).update(
                esito='confermata' if conferma else 'rifiutata')
            messages.success(request, fatto)
        return redirect('turni:notifiche')

    dip = getattr(request.user, 'dipendente', None)
    mittente = {'cambio': lambda: ogg.richiedente.utente, 'cambio_ufficio': lambda: ogg.richiedente.utente,
                'manutenzione': lambda: ogg.segnalata_da,
                'riunione': lambda: ogg.riunione.creata_da,
                'straordinaria': lambda: ogg.chiesta_da}.get(tipo, lambda: ogg.turno.dipendente.utente)()
    contesto = {'conferma': conferma, 'tipo': tipo, 'tondino': _tondino(mittente), 'ogg': ogg}
    if tipo == 'riunione':
        from .views_riunioni import quando as quando_riunione
        contesto.update(titolo=f'Riunione: {ogg.riunione.titolo}', quando=quando_riunione(ogg.riunione))
    elif tipo == 'cambio':
        contesto.update(titolo=f'{ogg.richiedente.nome_breve} ti chiede un cambio turno', righe=_righe_cambio(ogg, dip))
    elif tipo == 'cambio_ufficio':
        contesto.update(titolo=f'Cambio turno: {ogg.richiedente.nome_breve} ↔ {ogg.collega.nome_breve}',
                        persone=[(ogg.richiedente, _righe_cambio(ogg, ogg.richiedente)), (ogg.collega, _righe_cambio(ogg, ogg.collega))])
    elif tipo == 'manutenzione':
        contesto.update(titolo=f'Richiesta di manutenzione · {ogg.macchina.nome}')
    elif tipo == 'straordinaria':
        from .models import Luogo
        contesto.update(titolo=f'{ogg.get_tipo_display()} · {Luogo(ogg.luogo).label} · {ogg.giorno:%d/%m} {ogg.turno}: {ogg.testo}')
    else:
        contesto.update(titolo=f'{ogg.turno.dipendente.nome_breve} · {ogg.titolo}',
                        due_passaggi=tipo == 'pulizia_ct' and ogg.elemento_id
                        and ogg.elemento.convalida == ElementoPulizia.Convalida.CT_RP)
    return render(request, 'turni/notifica_scelta.html', contesto)
