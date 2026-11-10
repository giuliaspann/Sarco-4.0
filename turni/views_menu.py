"""Il quadrato centrale della barra (stile Instagram): tutte le funzioni dell'app, divise per sezione,
e la home dell'ufficio con le 4 funzioni più usate. Ognuno vede solo quello che può usare."""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

# icone a linea (stesso tratto dei riquadri di Oggi)
ICONE = {
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


def sezioni_per(request):
    from .context import navigazione
    from .manutenzione import e_manutentore, e_resp
    from .pulizie import e_resp_piazzale
    from .views import e_capoturno

    u = request.user
    nav = navigazione(request)
    dip = getattr(u, 'dipendente', None)
    ufficio = nav.get('nav_ufficio')
    mn = u.is_staff or e_resp(u) or e_manutentore(u)
    r = reverse
    sezioni = []

    lavoro = []
    if dip:
        lavoro += [voce('Pulizia', r('turni:pulizie'), 'pulizia'),
                   voce('Manutenzione', r('turni:mn_scelta'), 'manutenzione'),
                   voce('Produzione', r('turni:produzione_nuova'), 'produzione'),
                   voce('Analisi', r('turni:analisi_nuova'), 'analisi')]
    if dip or u.is_staff:
        lavoro += [voce('Fermo', r('turni:nuovo_fermo'), 'fermo'), voce('Ripartenza', r('turni:ripartenza'), 'riparti')]
    if e_capoturno(u, timezone.localdate()):
        lavoro.append(voce('Verifica', r('turni:capoturno'), 'verifica'))
    if e_resp_piazzale(u):
        lavoro.append(voce('Piazzale', r('turni:pulizie_piazzale'), 'piazzale'))
    if lavoro:
        sezioni.append(('In turno', lavoro))

    turni = []
    if dip:
        turni += [voce('I miei turni', r('turni:miei_turni'), 'calendario', nav.get('nav_area', 0)),
                  voce('Turni di tutti', r('turni:settimana_tutti'), 'tutti'),
                  voce('Squadra', r('turni:squadra'), 'squadra'),
                  voce('Cambio turno', r('turni:nuovo_cambio'), 'cambio'),
                  voce('Ritardo / uscita', r('turni:nuovo_avviso'), 'orologio'),
                  voce('Le mie richieste', r('turni:richieste'), 'richieste')]
    elif ufficio:
        turni += [voce('Turni di tutti', r('turni:settimana_tutti'), 'tutti'), voce('Squadra', r('turni:squadra'), 'squadra')]
    if turni:
        sezioni.append(('Turni', turni))

    manut = [voce('Interventi', r('turni:manutenzione'), 'manutenzione', nav.get('nav_manutenzione', 0)),
             voce('Avvisi', r('turni:comunicazioni'), 'avvisi')]
    if mn:
        manut += [voce('Macchine', r('turni:macchine'), 'macchine'), voce('Ricambi', r('turni:ricambi'), 'ricambi'),
                  voce('Ordini', r('turni:ordini'), 'ordini'), voce('Programmate', r('turni:programmate'), 'programmate')]
    sezioni.append(('Manutenzione', manut))

    dati = [voce('Statistiche', r('turni:statistiche'), 'statistiche'), voce('Produzione', r('turni:produzione'), 'produzione')]
    if nav.get('nav_report'):
        dati.append(voce('Report', r('turni:report'), 'report'))
    sezioni.append(('Dati', dati))

    archivio = [voce('Archivio', r('turni:archivio'), 'archivio'), voce('Pulizie', r('turni:archivio_pulizie'), 'foto'),
                voce('Analisi', r('turni:archivio_analisi'), 'analisi')]
    if ufficio:
        archivio.append(voce('Dipendenti', r('turni:archivio_dipendenti'), 'dipendenti'))
    sezioni.append(('Archivio', archivio))

    if ufficio:
        uff = []
        if nav.get('nav_responsabile'):
            uff += [voce('Richieste', r('turni:ufficio_richieste'), 'richieste', nav.get('nav_da_approvare', 0)),
                    voce('Turni extra', r('turni:ufficio_extra'), 'extra', nav.get('nav_volontari', 0))]
        if u.is_staff:
            uff += [voce('Carica turni', r('turni:importa'), 'carica'), voce('Dipendenti', r('turni:dipendenti'), 'dipendenti'),
                    voce('Assenze', r('turni:report_assenze'), 'report'),
                    voce('Mezzi e zone', r('admin:turni_elementopulizia_changelist'), 'zone')]
        if uff:
            sezioni.append(('Ufficio', uff))
    return sezioni


@login_required
def menu(request):
    return render(request, 'turni/menu.html', {'sezioni': sezioni_per(request)})


def home_ufficio(request):
    """Home di chi non ha turni (ufficio, responsabili): le 4 funzioni più usate, poi i fermi impianto."""
    from .context import navigazione
    from .models import FermoImpianto
    from .views import pulizie_da_verificare

    u = request.user
    nav = navigazione(request)
    r = reverse
    principali = []
    if nav.get('nav_responsabile'):
        principali.append(voce('Richieste', r('turni:ufficio_richieste'), 'richieste', nav.get('nav_da_approvare', 0)))
    if u.is_staff:
        principali.append(voce('Turni', r('turni:importa'), 'carica'))
    if nav.get('nav_capoturno'):  # l'ufficio vede le pulizie di tutti i turni
        principali.append(voce('Pulizie', r('turni:capoturno'), 'verifica', pulizie_da_verificare(u)))
    principali.append(voce('Manutenzione', r('turni:manutenzione'), 'manutenzione', nav.get('nav_manutenzione', 0)))
    if len(principali) < 4:
        principali.append(voce('Statistiche', r('turni:statistiche'), 'statistiche'))
    if len(principali) < 4 and u.is_staff:
        principali.append(voce('Dipendenti', r('turni:dipendenti'), 'dipendenti'))
    nome = (u.first_name or u.username).split()[0].capitalize()
    return render(request, 'turni/home_ufficio.html', {
        'principali': principali[:4],
        'nome': nome,
        'oggi_data': timezone.localdate(),
        'fermi_aperti': FermoImpianto.objects.filter(ripartito_il__isnull=True).order_by('fermo_dal'),
    })
