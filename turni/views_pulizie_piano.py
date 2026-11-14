"""Pagine delle pulizie per tutti i dipendenti (Giulia, 12/11/2026): Programma (Giorno · Settimana),
«In corso adesso» e la scheda della singola pulizia con i suoi passaggi e i tasti di chi deve agire."""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from . import piano_pulizie as pp
from .models import AvvisoPulizia, Dipendente, ElementoPulizia, Mansione, Pulizia, Turno

GIORNI = ['Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato', 'Domenica']
MESI = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre', 'ottobre', 'novembre',
        'dicembre']


def _data(valore, predefinita):
    from .views import leggi_data

    return leggi_data(valore, predefinita)


def _puo_straordinaria(utente):
    from .views_programma import puo_programmare

    return puo_programmare(utente, 'pulizia')


def _titolo_giorno(g):
    return f'{GIORNI[g.weekday()]} {g.day} {MESI[g.month - 1]}'


@login_required
def programma_pulizie(request):
    oggi = timezone.localdate()
    vista = 'settimana' if request.GET.get('vista') == 'settimana' else 'giorno'
    giorno = _data(request.GET.get('giorno'), oggi)
    area = request.GET.get('area', '')
    if area not in dict(pp.AREE):
        area = ''
    contesto = {'vista': vista, 'giorno': giorno, 'oggi': oggi, 'area': area, 'aree': pp.AREE,
                'puo_straordinaria': _puo_straordinaria(request.user)}
    if vista == 'giorno':
        piano = pp.piano_giorno(giorno, oggi)
        contesto.update(
            titolo=_titolo_giorno(giorno), prec=giorno - timedelta(days=1), succ=giorno + timedelta(days=1),
            blocchi=[{'sigla': s, 'nome': pp.NOMI[s][0], 'ore': pp.NOMI[s][1], 'classe': pp.CLASSI[s],
                      'voci': [v for v in piano[s] if not area or v['area'] == area]} for s in pp.ORDINE],
        )
        contesto['vuoto'] = not any(b['voci'] for b in contesto['blocchi'])
    else:
        lunedi = giorno - timedelta(days=giorno.weekday())
        giorni = [lunedi + timedelta(days=i) for i in range(7)]
        righe = {s: [] for s in pp.ORDINE}
        for g in giorni:
            piano = pp.piano_giorno(g, oggi)
            for s in pp.ORDINE:
                voci = [v for v in piano[s] if not area or v['area'] == area]
                c = pp.conteggi(voci)
                if not voci:
                    testo, classe = '–', 'vuota'
                elif g < oggi and c['ok'] == c['tot']:
                    testo, classe = '✓', 'tutte'
                elif g <= oggi:
                    testo, classe = f"{c['ok']}/{c['tot']}", 'tutte' if c['ok'] == c['tot'] else ('avanti' if c['avanti'] else 'ferme')
                else:
                    testo, classe = str(c['tot']), 'futura'
                speciale = any(v['settimanale'] or v['straordinaria'] for v in voci)
                righe[s].append({'giorno': g, 'testo': testo, 'classe': classe, 'speciale': speciale})
        fine = lunedi + timedelta(days=6)
        contesto.update(
            titolo=f'{lunedi.day}{" " + MESI[lunedi.month - 1] if lunedi.month != fine.month else ""} – {fine.day} {MESI[fine.month - 1]}',
            prec=lunedi - timedelta(days=7), succ=lunedi + timedelta(days=7),
            giorni=[{'data': g, 'sigla': GIORNI[g.weekday()][:3], 'oggi': g == oggi} for g in giorni],
            righe=[{'sigla': s, 'classe': pp.CLASSI[s], 'celle': righe[s]} for s in pp.ORDINE],
        )
    return render(request, 'turni/pulizie_programma.html', contesto)


def _fasce_in_corso(adesso):
    """I turni che stanno lavorando adesso (es. alle 10: 1° turno e giornaliero)."""
    ore = adesso.hour + adesso.minute / 60
    attivi = set()
    if 6 <= ore < 14:
        attivi.add('1T')
    if 14 <= ore < 22:
        attivi.add('2T')
    if 8 <= ore < 17.5:
        attivi.add('G')
    if ore >= 22 or ore < 6:
        attivi.add('N')
    return attivi


@login_required
def pulizie_adesso(request):
    """Timeline 4 (Giulia, 12/11): i turni del giorno in ordine 1T, 2T, G, N con la barra di avanzamento;
    quello in corso è aperto e mostra le pulizie divise per impianto."""
    adesso = timezone.localtime()
    oggi = adesso.date()
    giorno = _data(request.GET.get('giorno'), oggi)
    piano = pp.piano_giorno(giorno, oggi)
    # prima delle 6 la notte in corso è quella cominciata ieri
    notte_ieri = giorno == oggi and adesso.hour < 6
    if notte_ieri:
        piano['N'] = pp.piano_giorno(oggi - timedelta(days=1), oggi)['N']
    attivi = _fasce_in_corso(adesso) if giorno == oggi else set()
    aperto = request.GET.get('apri', '')
    turni = []
    for s in pp.ORDINE:
        voci = piano[s]
        c = pp.conteggi(voci)
        aree = []
        for a, nome in pp.AREE:
            del_area = [v for v in voci if v['area'] == a]
            if del_area:
                aree.append({'nome': nome, 'voci': del_area})
        turni.append({
            'sigla': s, 'nome': pp.NOMI[s][0] + (' (da ieri sera)' if s == 'N' and notte_ieri else ''), 'ore': pp.NOMI[s][1],
            'classe': pp.CLASSI[s], 'adesso': s in attivi, 'aperto': (s == aperto) or (not aperto and s in attivi),
            'aree': aree, 'ok': c['ok'], 'tot': c['tot'], 'perc': 5 * round(20 * c['ok'] / c['tot']) if c['tot'] else 0,
        })
    return render(request, 'turni/pulizie_adesso.html', {
        'turni': turni, 'giorno': giorno, 'titolo': _titolo_giorno(giorno), 'ora': adesso if giorno == oggi else None,
        'prec': giorno - timedelta(days=1), 'succ': giorno + timedelta(days=1), 'oggi': oggi,
    })


# ---------------------------------------------------------------- scheda della singola pulizia

def gruppo_di(p):
    """La stessa voce, lo stesso giorno e turno (es. le macchine ottiche dei due operatori)."""
    if not p.elemento_id:
        return [p]
    return list(Pulizia.objects.filter(elemento=p.elemento, turno__data=p.turno.data, turno__fascia__in=pp.fasce_di(pp.sigla(p.turno.fascia)))
                .select_related('turno__dipendente', 'elemento', 'fatta_da', 'ok_capoturno_da__dipendente',
                                'ok_manutentore_da__dipendente', 'verificata_da__dipendente').order_by('pk'))


def _e_capo(utente, p):
    from .views import fasce_del_capo

    f = pp.FASCE[pp.sigla(p.turno.fascia)]
    return f in fasce_del_capo(utente, p.turno.data)


def _e_manutentore(utente, p):
    from .pulizie import manutentore_del_turno

    m = manutentore_del_turno(p.turno)
    dip = getattr(utente, 'dipendente', None)
    return bool(dip and ((m and m.dipendente_id == dip.pk) or Mansione.MANUTENTORE in dip.mansioni))


def _chi(u):
    if u is None:
        return ''
    return getattr(getattr(u, 'dipendente', None), 'nome_breve', '') or u.get_username()


def passaggi(righe):
    """I passaggi della pulizia, come nella timeline 1: fatto (verde), in corso (giallo) o ancora da fare (grigio)."""
    p = righe[0]
    e = p.elemento
    via = pp.percorso(p)
    ora = lambda d: timezone.localtime(d).strftime('%H:%M') if d else ''  # noqa: E731
    primo = lambda campo: min((getattr(r, campo) for r in righe if getattr(r, campo)), default=None)  # noqa: E731
    fatta = primo('fatta_il')
    passi = []
    if e and e.avviso:
        inviato = AvvisoPulizia.objects.filter(chiave=f'{e.pk}-{p.turno.data.isoformat()}-{pp.sigla(p.turno.fascia)}').first()
        passi.append({'testo': 'Avviso ' + pp.quando_di(e), 'ora': ora(inviato.inviato_il) if inviato else '', 'fatto': bool(inviato)})
    if e and e.con_avvio:
        iniziata = primo('iniziata_il')
        passi.append({'testo': 'Pulizia iniziata', 'ora': ora(iniziata), 'fatto': bool(iniziata)})
        man = primo('ok_manutentore_il')
        chi_m = next((_chi(r.ok_manutentore_da) for r in righe if r.ok_manutentore_da_id), '')
        passi.append({'testo': 'Manutentore: completato' + (f' ({chi_m})' if chi_m else ''), 'ora': ora(man), 'fatto': bool(man),
                      'attesa': bool(iniziata and not man)})
    tutte_fatte = all(r.stato != Pulizia.Stato.DA_FARE for r in righe)
    chi_f = ', '.join(dict.fromkeys(r.fatta_da.nome_breve for r in righe if r.fatta_da_id))
    passi.append({'testo': ('Conclusa' if not e or not e.controllo else 'Controllo fatto') + (f' · fatta da {chi_f}' if chi_f else ''),
                  'ora': ora(fatta), 'fatto': tutte_fatte})
    if via == 'CT_RP':
        ok = primo('ok_capoturno_il')
        chi_c = next((_chi(r.ok_capoturno_da) for r in righe if r.ok_capoturno_da_id), '')
        passi.append({'testo': 'Confermata dal Capo Turno' + (f' ({chi_c})' if chi_c else ''), 'ora': ora(ok),
                      'fatto': all(r.ok_capoturno_il or r.stato == Pulizia.Stato.VERIFICATA for r in righe),
                      'attesa': tutte_fatte and not ok})
    if via != 'NESSUNA':
        conv = [r for r in righe if r.stato == Pulizia.Stato.VERIFICATA]
        rifare = any(r.stato == Pulizia.Stato.SEGNALATA for r in righe)
        passi.append({'testo': 'Da rifare (responsabile piazzale)' if rifare else 'Convalidata dal responsabile piazzale',
                      'ora': ora(max((r.verificata_il for r in conv if r.verificata_il), default=None)),
                      'fatto': len(conv) == len(righe), 'no': rifare,
                      'attesa': any(pp.va_al_rp(r) for r in righe)})
    return passi


def _avvisa_rp(utente, p):
    from . import manutenzione as mn
    from .pulizie import resp_piazzale

    mn.avvisa(resp_piazzale(), utente, f'✅ {p.titolo} · {p.turno.dipendente.nome_breve}', 'Confermata dal Capo Turno: da convalidare',
              reverse('turni:pulizie_piazzale') + f'#p-{p.pk}', tipo='pulizia_rp', oggetto_id=p.pk)


@login_required
def pulizia_voce(request, pk):
    from .pulizie import usa_telefono

    p = get_object_or_404(Pulizia.objects.select_related('turno__dipendente', 'elemento'), pk=pk)
    righe = gruppo_di(p)
    e = p.elemento
    capo = _e_capo(request.user, p)
    manut = _e_manutentore(request.user, p)
    dip = getattr(request.user, 'dipendente', None)
    mie = [r for r in righe if dip and r.turno.dipendente_id == dip.pk and usa_telefono(r.turno)
           and r.stato in (Pulizia.Stato.DA_FARE, Pulizia.Stato.SEGNALATA)]
    da_fare = [r for r in righe if r.stato in (Pulizia.Stato.DA_FARE, Pulizia.Stato.SEGNALATA)]
    iniziata = any(r.iniziata_il for r in righe)
    ok_man = any(r.ok_manutentore_il for r in righe)
    torna = reverse('turni:pulizia_voce', args=[p.pk])

    if request.method == 'POST':
        azione = request.POST.get('azione')
        adesso = timezone.now()
        if azione == 'iniziata' and e and e.con_avvio and da_fare and capo:
            Pulizia.objects.filter(pk__in=[r.pk for r in da_fare]).update(iniziata_il=adesso)
            messages.success(request, f'{e.nome}: pulizia iniziata.')
        elif azione == 'manutentore' and e and e.con_avvio and capo:
            fatto = request.POST.get('fatto') == '1'
            Pulizia.objects.filter(pk__in=[r.pk for r in righe]).update(
                ok_manutentore_il=adesso if fatto else None, ok_manutentore_da=request.user if fatto else None)
            messages.success(request, 'Spunta del manutentore segnata.' if fatto else 'Spunta del manutentore tolta.')
        elif azione in ('conclusa', 'conferma') and capo and da_fare:
            if e and e.con_avvio and not ok_man:
                messages.error(request, 'Prima serve la spunta «Manutentore: completato».')
                return redirect(torna)
            foto = request.FILES.get('foto')
            serve_foto = e and e.modo in (ElementoPulizia.Modo.PULIZIA_FOTO, ElementoPulizia.Modo.FOTO_DOPO, ElementoPulizia.Modo.CONTROLLO_FOTO)
            if serve_foto and not foto and not all(r.foto for r in da_fare):
                messages.error(request, 'Serve la foto della pulizia finita.')
                return redirect(torna)
            # chi l'ha fatta davvero (a volte un collega libero in quel momento)
            fatta_da = None
            scelto = request.POST.get('fatta_da') or ''
            if scelto.isdigit():
                fatta_da = Dipendente.objects.filter(pk=scelto, attivo=True).first()
            from .pulizie import salva_foto

            for r in da_fare:
                if foto:
                    foto.seek(0)
                    try:
                        salva_foto(r, foto)
                    except Exception:
                        messages.error(request, 'La foto non si legge: riprova a scattarla.')
                        return redirect(torna)
                r.stato, r.fatta_il = Pulizia.Stato.FATTA, adesso
                if fatta_da and len(da_fare) == 1:
                    r.fatta_da = fatta_da
                r.nota = (request.POST.get('nota') or '').strip()[:300] or r.nota
                r.ok_capoturno_da, r.ok_capoturno_il = request.user, adesso
                if pp.percorso(r) == 'NESSUNA':
                    r.stato, r.verificata_il = Pulizia.Stato.VERIFICATA, adesso
                r.save()
            if pp.percorso(da_fare[0]) != 'NESSUNA':
                _avvisa_rp(request.user, da_fare[0])
            messages.success(request, f'{p.titolo}: confermata, inviata al responsabile piazzale.')
        elif azione == 'non_ancora' and capo:
            messages.info(request, 'Va bene: confermala quando è fatta.')
        else:
            messages.error(request, 'Questa azione adesso non è possibile.')
        return redirect(torna)

    # chi può aver fatto la pulizia: chi lavora in quel turno (per cambiare il nome, es. pozzetti)
    colleghi = []
    if capo and da_fare and len(da_fare) == 1:
        colleghi = [t.dipendente for t in Turno.objects.filter(
            data=p.turno.data, fascia__in=pp.fasce_di(pp.sigla(p.turno.fascia)), dipendente__attivo=True, capoturno=False)
            .select_related('dipendente').order_by('dipendente__nome') if t.lavora]
    s = pp.sigla(p.turno.fascia)
    return render(request, 'turni/pulizia_voce.html', {
        'p': p, 'righe': righe, 'e': e, 'passi': passaggi(righe),
        'persone': [r.fatta_da.nome_breve if r.fatta_da_id else r.turno.dipendente.nome_breve for r in righe],
        'sigla': s, 'classe': pp.CLASSI.get(s, ''), 'nome_turno': pp.NOMI.get(s, ('', ''))[0],
        'area': dict(pp.AREE).get(pp.area_di(p.turno, e), ''), 'quando': pp.quando_di(e),
        'stato': pp.STATI[pp.stato_gruppo([pp.stato_di(r) for r in righe])],
        'capo': capo, 'manut': manut, 'mie': mie, 'da_fare': da_fare, 'iniziata': iniziata, 'ok_man': ok_man,
        'colleghi': colleghi, 'assegnata_a': da_fare[0].turno.dipendente_id if len(da_fare) == 1 else None,
        'via_ct': pp.percorso(p) == 'CT_RP', 'serve_foto': bool(e and e.modo in (
            ElementoPulizia.Modo.PULIZIA_FOTO, ElementoPulizia.Modo.FOTO_DOPO, ElementoPulizia.Modo.CONTROLLO_FOTO)),
        'nome_corto': pp.nome_corto(e) if e else '',
    })


# ---------------------------------------------------------------- richieste al responsabile piazzale (Giulia, 13/11/2026)

@login_required
def richiesta_rp(request, pk):
    """Il RP vede la richiesta (cosa, dove, quando, chi la chiede, foto) e la assegna a chi lavora in quel turno, o la rifiuta."""
    from django.core.exceptions import PermissionDenied

    from .models import Luogo, Straordinaria
    from .pulizie import approva_richiesta, e_resp_piazzale, in_turno, rifiuta_richiesta

    s = get_object_or_404(Straordinaria.objects.select_related('chiesta_da__dipendente'), pk=pk)
    rp = e_resp_piazzale(request.user)
    if not rp and s.chiesta_da_id != request.user.pk:
        raise PermissionDenied
    fascia = s.turno if s.turno in ('1T', '2T', 'N', 'G') else '1T'
    vicini, altri = in_turno(s.giorno, fascia, s.luogo)
    capo = next((t for t in vicini + altri if t.capoturno), None)
    if request.method == 'POST' and rp and s.stato == Straordinaria.Stato.ATTESA:
        if request.POST.get('azione') == 'approva':
            t = next((x for x in vicini + altri if str(x.pk) == request.POST.get('turno')), None)
            if not t:
                messages.error(request, 'Scegli a chi assegnarla.')
                return redirect('turni:richiesta_rp', s.pk)
            approva_richiesta(request.user, s, t)
            messages.success(request, f'Pulizia approvata e assegnata a {t.dipendente.nome_breve}.')
        elif request.POST.get('azione') == 'rifiuta':
            rifiuta_richiesta(request.user, s, (request.POST.get('nota') or '').strip())
            messages.success(request, 'Richiesta non approvata: avvisato chi l\'aveva chiesta.')
        from .models import Notifica

        Notifica.objects.filter(utente=request.user, tipo='straordinaria', oggetto_id=s.pk).update(
            esito='confermata' if s.stato == Straordinaria.Stato.INOLTRATA else 'rifiutata')
        return redirect('turni:pulizie_piazzale')
    return render(request, 'turni/richiesta_rp.html', {
        's': s, 'rp': rp, 'nome_luogo': Luogo(s.luogo).label if s.luogo in Luogo.values else s.luogo,
        'chi': getattr(getattr(s.chiesta_da, 'dipendente', None), 'nome_breve', '') or (s.chiesta_da.get_username() if s.chiesta_da else ''),
        'persone': vicini + altri, 'proposto': capo.pk if capo else None, 'classe': pp.CLASSI.get(fascia, ''),
        'nome_turno': pp.NOMI.get(fascia, ('', ''))[0],
    })


@login_required
def foto_richiesta_rp(request, pk):
    from django.core.exceptions import PermissionDenied
    from django.http import FileResponse, Http404

    from .models import Straordinaria
    from .pulizie import e_resp_piazzale

    s = get_object_or_404(Straordinaria, pk=pk)
    if not (e_resp_piazzale(request.user) or s.chiesta_da_id == request.user.pk):
        raise PermissionDenied
    if not s.foto:
        raise Http404
    return FileResponse(s.foto.open('rb'), content_type='image/jpeg')
