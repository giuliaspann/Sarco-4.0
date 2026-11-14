"""Programma manutenzione / Programma pulizia (Giulia, 10/11/2026).

Stessi passaggi per tutte e due: dove, cosa, il giorno e il turno. Il fermo impianto è facoltativo:
con «Programma anche fermo impianto» si sceglie l'impianto e, se non serve tutto il turno, la fascia oraria.
Il fermo programmato avvisa tutti gli interessati: chi lavora in quel turno su quell'impianto, i Capi Turno
di quel turno, i manutentori e i responsabili.
"""

from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from . import manutenzione as mn
from .models import Comunicazione, Dipendente, Fascia, FermoImpianto, Intervento, Luogo, Macchina, Turno
from .pulizie import POSTAZIONI_AREA

LUOGHI = [Luogo.IMP1, Luogo.IMP2, Luogo.PIAZZALE, Luogo.METALLI, Luogo.SABBIA, Luogo.MEZZI, Luogo.ANALISI]
TURNI = [('1T', '1° turno · 06–14'), ('2T', '2° turno · 14–22'), ('N', 'Notturno · 22–06')]
ORARI = {'1T': (time(6), time(14)), '2T': (time(14), time(22)), 'N': (time(22), time(6))}
FASCIA_DI = {'1T': Fascia.MATTINA, '2T': Fascia.POMERIGGIO, 'N': Fascia.NOTTE}


def puo_programmare(utente, cosa='manutenzione'):
    """Manutenzione: Capo Turno in servizio, responsabili, ufficio. Pulizia straordinaria: tutti
    (chi non è il RP la manda al RP, Giulia 13/11/2026)."""
    from .views import e_capoturno

    if cosa == 'pulizia':
        return utente.is_authenticated and (utente.is_staff or getattr(utente, 'dipendente', None) is not None)

    dip = getattr(utente, 'dipendente', None)
    return (utente.is_staff or e_capoturno(utente, timezone.localdate())
            or bool(dip and (dip.resp_impianto or dip.resp_piazzale or dip.resp_manutenzione)))


def _orario(giorno, turno, dalle='', alle=''):
    """Inizio e fine del fermo: tutto il turno, oppure la fascia oraria scelta dentro il turno."""
    inizio, fine = ORARI[turno]
    try:
        if dalle:
            inizio = time.fromisoformat(dalle)
        if alle:
            fine = time.fromisoformat(alle)
    except ValueError:
        pass
    dal = timezone.make_aware(datetime.combine(giorno, inizio))
    # il notturno (e una fascia che passa la mezzanotte) finisce il giorno dopo
    if turno == 'N' and inizio < time(12):
        dal += timedelta(days=1)
    al = timezone.make_aware(datetime.combine(giorno, fine))
    if al <= dal:
        al += timedelta(days=1)
    return dal, al


def interessati(giorno, turno, impianto):
    """Chi avvisare di un fermo programmato."""
    postazioni = POSTAZIONI_AREA.get(impianto, [impianto])
    turni = Turno.objects.filter(data=giorno, fascia=FASCIA_DI[turno], dipendente__attivo=True).select_related('dipendente')
    ids = [t.dipendente.utente_id for t in turni if t.postazione in postazioni or t.capoturno]
    ids += [d.utente_id for d in mn.manutentori()] + mn.responsabili()
    ids += list(Dipendente.objects.filter(attivo=True).filter(resp_impianto=True).values_list('utente_id', flat=True))
    ids += list(Dipendente.objects.filter(attivo=True).filter(resp_piazzale=True).values_list('utente_id', flat=True))
    return [i for i in dict.fromkeys(ids) if i]


def programma_fermo(utente, motivo, giorno, turno, impianto, dalle, alle, testo, macchina=None):
    dal, al = _orario(giorno, turno, dalle, alle)
    c = Comunicazione.objects.create(
        tipo=Comunicazione.Tipo.FERMO, testo=testo, luogo=impianto, fascia=turno, macchina=macchina, dal=dal, al=al,
        destinatari=Comunicazione.A.TUTTI, autore=utente, motivo=motivo,
    )
    nome = dict(FermoImpianto.IMPIANTI).get(impianto) or Luogo(impianto).label
    quando = f'{giorno:%a %d/%m} {timezone.localtime(dal):%H:%M}–{timezone.localtime(al):%H:%M}'
    mn.avvisa(interessati(giorno, turno, impianto), utente, f'Fermo programmato · {nome}',
              f'{quando} · {c.get_motivo_display().lower()}: {testo}', reverse('turni:comunicazione', args=[c.pk]))
    return c


@login_required
def programma(request, cosa):
    if cosa not in ('manutenzione', 'pulizia'):
        raise PermissionDenied
    if not puo_programmare(request.user, cosa):
        raise PermissionDenied
    indietro = reverse('turni:mn_scelta') if cosa == 'manutenzione' else reverse('turni:pulizie')
    # il fermo impianto vero (non la pulizia in sé) resta riservato a chi potrebbe programmarlo
    # anche da «Programma manutenzione»: Capo Turno in servizio, responsabili, ufficio (Giulia, 14/11/2026)
    puo_fermo = cosa == 'manutenzione' or puo_programmare(request.user, 'manutenzione')
    luogo = request.POST.get('luogo') or request.GET.get('luogo') or ''
    if luogo not in Luogo.values:
        return render(request, 'turni/programma.html', {'cosa': cosa, 'passo': 'dove', 'indietro': indietro,
                                                         'luoghi': [(v, Luogo(v).label) for v in LUOGHI],
                                                         'puo_fermo': puo_fermo})
    macchine = Macchina.objects.filter(attiva=True, luogo=luogo).exclude(tipo=Macchina.Tipo.SEGNALETICA).order_by('nome')
    domani = timezone.localdate() + timedelta(days=1)
    if request.method == 'POST':
        testo = (request.POST.get('descrizione') or '').strip()[:1000]
        turno = request.POST.get('turno') or ''
        try:
            giorno = date.fromisoformat(request.POST.get('giorno') or '')
        except ValueError:
            giorno = None
        fermo = request.POST.get('fermo') == '1'
        impianto = luogo if luogo in dict(FermoImpianto.IMPIANTI) else (request.POST.get('impianto') or '')
        scelta = request.POST.get('macchina') or ''
        macchina = macchine.filter(pk=scelta).first() if scelta.isdigit() else None
        errore = ''
        if cosa == 'manutenzione' and not macchina:
            errore = 'Scegli su cosa va fatta la manutenzione.'
        elif not testo:
            errore = 'Scrivi cosa va fatto.'
        elif not giorno or giorno < timezone.localdate():
            errore = 'Scegli il giorno (da oggi in poi).'
        elif turno not in ORARI:
            errore = 'Scegli il turno.'
        elif fermo and not puo_fermo:
            errore = 'Non puoi programmare anche il fermo impianto.'
        elif fermo and impianto not in dict(FermoImpianto.IMPIANTI):
            errore = "Scegli quale impianto sarà fermo."
        if errore:
            messages.error(request, errore)
        else:
            if cosa == 'manutenzione':
                i = Intervento.objects.create(
                    macchina=macchina, tipo=Intervento.Tipo.PROGRAMMATA, descrizione=testo, segnalata_da=request.user,
                    da_fare_il=giorno, priorita=Intervento.Priorita.NORMALE,
                )
                mn.evento(i, request.user, f'Programmata per {giorno:%d/%m} ({dict(TURNI)[turno].split(" ·")[0]})')
                mn.avvisa(mn.responsabili(), request.user, f'Manutenzione programmata · {macchina.nome}',
                          f'{giorno:%a %d/%m} {dict(TURNI)[turno].split(" ·")[0]}: {testo}', mn.url_intervento(i))
                fatto = f'Manutenzione programmata su {macchina.nome} per {giorno:%d/%m}'
            else:
                fatto = _programma_pulizia(request.user, luogo, giorno, turno, testo)
            if fermo:
                programma_fermo(request.user, Comunicazione.Motivo.MANUTENZIONE if cosa == 'manutenzione' else Comunicazione.Motivo.PULIZIA,
                                giorno, turno, impianto, request.POST.get('dalle') or '', request.POST.get('alle') or '', testo,
                                macchina)
                fatto += ', con fermo impianto: avvisati tutti gli interessati'
            messages.success(request, fatto + '.')
            return redirect(indietro)
    return render(request, 'turni/programma.html', {
        'cosa': cosa, 'passo': 'cosa', 'indietro': indietro, 'luogo': luogo, 'nome_luogo': Luogo(luogo).label,
        'macchine': macchine if cosa == 'manutenzione' else None, 'turni': TURNI, 'domani': domani.isoformat(),
        'oggi': timezone.localdate().isoformat(),
        'impianti': FermoImpianto.IMPIANTI, 'impianto_proposto': luogo if luogo in dict(FermoImpianto.IMPIANTI) else '',
        'puo_fermo': puo_fermo,
    })


def _programma_pulizia(utente, luogo, giorno, turno, testo):
    """La assegna direttamente solo il responsabile piazzale (al Capo Turno di quel giorno e turno); gli altri
    la mandano al RP, che la approva e la assegna (Giulia, 13/11/2026)."""
    from .models import Straordinaria
    from .pulizie import chiedi_al_rp, e_resp_piazzale

    if not e_resp_piazzale(utente):
        chiedi_al_rp(utente, Straordinaria.Tipo.STRAORDINARIA, luogo, giorno, turno, testo)
        return f'Pulizia straordinaria in {Luogo(luogo).label} per {giorno:%d/%m}: la riceve il responsabile piazzale, che la assegna'
    return _al_capo(utente, luogo, giorno, turno, testo)


def _al_capo(utente, luogo, giorno, turno, testo):
    from .pulizie import richiedi_pulizia

    turni = Turno.objects.filter(data=giorno, fascia=FASCIA_DI[turno], capoturno=True, dipendente__attivo=True).select_related('dipendente')
    vicini = POSTAZIONI_AREA.get(luogo, [luogo])
    capo = next((t for t in turni if t.postazione in vicini), None) or turni.first()
    nome = Luogo(luogo).label
    if not capo:
        return f'Pulizia programmata in {nome} per {giorno:%d/%m}: i turni di quel giorno non sono ancora caricati, assegnala al Capo Turno quando ci sono'
    richiedi_pulizia(utente, capo, None, f'{nome} · {testo}')
    return f'Pulizia programmata in {nome} per {giorno:%d/%m}: la riceve il Capo Turno {capo.dipendente.nome_breve}'
