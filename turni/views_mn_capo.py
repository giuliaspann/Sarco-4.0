"""Manutenzione dal Capo Turno (Giulia, 10/11/2026).

«Manutenzione in corso»: su cosa si lavora (macchina o mezzo) e cosa si fa; il fermo impianto è facoltativo,
con l'ora in cui l'impianto si è fermato. «Manutenzione conclusa»: l'elenco delle manutenzioni in corso;
si chiude con una foto (facoltativa) e, se avevano fermato l'impianto, la ripartenza con l'ora.
Le ore partono da adesso (la segnalazione si fa quasi sempre in diretta) e si possono correggere.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from . import manutenzione as mn
from .models import FermoImpianto, Intervento, Luogo, Macchina
from .views_manutenzione import _quando

# dove si può lavorare (come nella segnalazione guasti), senza i mezzi delle ditte esterne
LUOGHI = [Luogo.IMP1, Luogo.IMP2, Luogo.PIAZZALE, Luogo.METALLI, Luogo.SABBIA, Luogo.MEZZI, Luogo.ANALISI]


def _adesso():
    return timezone.localtime().strftime('%Y-%m-%dT%H:%M')


@login_required
def in_corso(request):
    luogo = request.POST.get('luogo') or request.GET.get('luogo') or ''
    if luogo not in Luogo.values:
        return render(request, 'turni/mn_capo_in_corso.html', {'passo': 'dove', 'luoghi': [(v, Luogo(v).label) for v in LUOGHI]})
    macchine = Macchina.objects.filter(attiva=True, luogo=luogo).exclude(tipo=Macchina.Tipo.SEGNALETICA).order_by('nome')
    if request.method == 'POST':
        scelta = request.POST.get('macchina') or ''
        macchina = macchine.filter(pk=scelta).first() if scelta.isdigit() else None
        descrizione = (request.POST.get('descrizione') or '').strip()[:1000]
        fermo = request.POST.get('fermo') == '1'
        # se la manutenzione è in un impianto, il fermo è di quell'impianto
        impianto = luogo if luogo in dict(FermoImpianto.IMPIANTI) else (request.POST.get('impianto') or '')
        if not macchina:
            messages.error(request, 'Scegli su cosa si sta facendo la manutenzione.')
        elif not descrizione:
            messages.error(request, 'Scrivi che manutenzione si sta facendo.')
        elif fermo and impianto not in dict(FermoImpianto.IMPIANTI):
            messages.error(request, 'Scegli quale impianto si è fermato.')
        else:
            dal = _quando(request.POST.get('dal')) if fermo else timezone.now()
            i = Intervento.objects.create(
                macchina=macchina, tipo=Intervento.Tipo.LAVORO, descrizione=descrizione, macchina_ferma=fermo,
                stato=Intervento.Stato.IN_CORSO, segnalata_da=request.user, segnalata_il=dal, iniziata_il=dal,
            )
            mn.evento(i, request.user, 'Manutenzione in corso')
            if fermo:
                f = FermoImpianto.objects.create(
                    impianto=impianto, causa=FermoImpianto.Causa.MANUTENZ, macchina=macchina, descrizione=descrizione[:500],
                    fermo_dal=dal, segnalato_da=request.user, intervento=i,
                )
                mn.avvisa(mn.chi_avvisare_fermo(), request.user, f'{f.get_impianto_display()} fermo per manutenzione',
                          f'{macchina.nome}: {descrizione}', reverse('turni:fermo', args=[f.pk]))
                messages.success(request, f'Manutenzione in corso su {macchina.nome}; {f.get_impianto_display()} fermo '
                                          f'dalle {timezone.localtime(dal):%H:%M}.')
            else:
                mn.avvisa(mn.responsabili(), request.user, f'Manutenzione in corso · {macchina.nome}', descrizione,
                          mn.url_intervento(i))
                messages.success(request, f'Manutenzione in corso su {macchina.nome}.')
            return redirect('turni:mn_scelta')
    return render(request, 'turni/mn_capo_in_corso.html', {
        'passo': 'cosa', 'luogo': luogo, 'nome_luogo': Luogo(luogo).label, 'macchine': macchine,
        'impianti': FermoImpianto.IMPIANTI, 'impianto_proposto': luogo if luogo in dict(FermoImpianto.IMPIANTI) else '',
        'adesso': _adesso(),
    })


@login_required
def conclusa(request):
    """Le manutenzioni in corso, da concludere."""
    aperte = (Intervento.objects.filter(stato=Intervento.Stato.IN_CORSO)
              .select_related('macchina', 'segnalata_da__dipendente').prefetch_related('fermi').order_by('-iniziata_il'))
    for i in aperte:
        i.fermo_aperto = next((f for f in i.fermi.all() if f.ripartito_il is None), None)
    return render(request, 'turni/mn_capo_conclusa.html', {'aperte': aperte})


@login_required
def concludi(request, intervento_id):
    i = get_object_or_404(Intervento.objects.select_related('macchina'), pk=intervento_id, stato=Intervento.Stato.IN_CORSO)
    fermo = i.fermi.filter(ripartito_il__isnull=True).first()
    if request.method == 'POST':
        lavoro = (request.POST.get('lavoro') or '').strip()[:1000]
        quando = _quando(request.POST.get('ripartito')) if fermo and request.POST.get('riparte') == '1' else None
        if quando and quando < fermo.fermo_dal:
            messages.error(request, "L'ora di ripartenza è prima dell'inizio del fermo.")
        else:
            try:
                if request.FILES.get('foto'):
                    i.foto_riparazione.save('lavoro.jpg', mn.comprimi_foto(request.FILES['foto']), save=False)
            except (ValueError, OSError):
                messages.error(request, 'La foto non è valida: riprova.')
                return redirect('turni:mn_concludi', i.pk)
            i.stato = Intervento.Stato.COMPLETATA
            i.completata_il, i.completata_da = timezone.now(), request.user
            i.lavoro_svolto = lavoro or i.lavoro_svolto
            i.save()
            mn.evento(i, request.user, 'Manutenzione conclusa' + (f': {lavoro}' if lavoro else ''))
            if quando:
                mn.fai_ripartire(request.user, fermo, quando, lavoro)
            mn.avvisa(mn.responsabili() + [i.segnalata_da_id], request.user, f'Manutenzione conclusa · {i.macchina.nome}',
                      lavoro or i.descrizione, mn.url_intervento(i))
            messages.success(request, f'Manutenzione conclusa su {i.macchina.nome}'
                                      + (f'; {fermo.get_impianto_display()} ripartito alle {timezone.localtime(quando):%H:%M}.' if quando else '.'))
            return redirect('turni:mn_conclusa')
    return render(request, 'turni/mn_capo_concludi.html', {'i': i, 'fermo': fermo, 'adesso': _adesso()})
