"""Documenti dei dipendenti (cedolini, contratti, attestati) e aziendali, anagrafica e scadenze.

I file stanno nel volume con un nome casuale e si scaricano solo da qui: ognuno vede i suoi e
quelli aziendali, l'ufficio vede tutto.
"""

import re
from datetime import date, timedelta
from pathlib import Path

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .models import Dipendente, Documento, LetturaDocumento, Scadenza, TipoContratto
from .views import dipendente_di

ESTENSIONI = {'.pdf', '.jpg', '.jpeg', '.png', '.doc', '.docx', '.xls', '.xlsx', '.odt'}
MAX_MB = 15
# le scadenze entro questi giorni compaiono in evidenza all'ufficio
PREAVVISO_GIORNI = 30
WHISTLEBLOWING_URL = 'https://sarcosrl.it/whistleblowing/'


def documenti_per(dip):
    return Documento.objects.filter(Q(dipendente=dip) | Q(dipendente__isnull=True))


def da_leggere(dip):
    """Documenti nuovi (mai aperti) o con la presa visione ancora da dare."""
    if not dip:
        return 0
    letture = dict(LetturaDocumento.objects.filter(dipendente=dip).values_list('documento_id', 'presa_visione_il'))
    return sum(
        1
        for pk, chiedi in documenti_per(dip).values_list('pk', 'chiedi_presa_visione')
        if pk not in letture or (chiedi and not letture[pk])
    )


def scadenze_vicine():
    limite = timezone.localdate() + timedelta(days=PREAVVISO_GIORNI)
    vicine = list(Scadenza.objects.filter(dipendente__attivo=True, scade_il__lte=limite).select_related('dipendente'))
    contratti = Dipendente.objects.filter(attivo=True, scadenza_contratto__lte=limite).order_by('scadenza_contratto')
    for d in contratti:
        vicine.append(Scadenza(dipendente=d, tipo=Scadenza.Tipo.ALTRO, descrizione='Fine contratto', scade_il=d.scadenza_contratto))
    return sorted(vicine, key=lambda s: s.scade_il)


def _parole(testo):
    return set(slugify(testo.replace("'", ' ').replace('_', ' ')).split('-'))


def dipendente_dal_nome_file(nome_file, dipendenti):
    """ROSSI_MARIO_cedolino_09-2026.pdf -> Rossi Mario: tutte le parole del nome nel nome del file.
    Se ne combaciano due (omonimi parziali) vince quello col nome più lungo; se resta un pari, nessuno."""
    parole = _parole(Path(nome_file).stem)
    trovati = [d for d in dipendenti if (_parole(d.nome) - {''}) <= parole]
    if not trovati:
        return None
    trovati.sort(key=lambda d: -len(_parole(d.nome)))
    if len(trovati) > 1 and len(_parole(trovati[0].nome)) == len(_parole(trovati[1].nome)):
        return None
    return trovati[0]


def _file_valido(f):
    if Path(f.name).suffix.lower() not in ESTENSIONI:
        return f'{f.name}: formato non accettato (PDF, immagini, Word, Excel).'
    if f.size > MAX_MB * 1024 * 1024:
        return f'{f.name}: troppo grande (massimo {MAX_MB} MB).'
    return None


def _torna(request, predefinito='turni:ufficio_documenti'):
    # solo pagine interne dell'app, mai un indirizzo esterno
    torna = request.POST.get('torna') or ''
    return torna if torna.startswith('/turni/') and '//' not in torna else predefinito


def _avvisa(documenti):
    from . import push

    per_utente = {}
    tutti = False
    for d in documenti:
        if d.aziendale:
            tutti = d
        elif d.dipendente.utente_id:
            per_utente[d.dipendente.utente_id] = d
    url = reverse('turni:documenti')
    if tutti:
        ids = Dipendente.objects.filter(attivo=True, utente__isnull=False).values_list('utente_id', flat=True)
        push.invia(ids, 'Nuovo documento aziendale', tutti.titolo, url)
    for uid, d in per_utente.items():
        push.invia([uid], 'Nuovo documento per te', d.titolo, url)


# ---------------------------------------------------------------- dipendente


@login_required
def documenti(request):
    dip = dipendente_di(request)
    if not dip:
        if request.user.is_staff:
            return redirect('turni:ufficio_documenti')
        raise PermissionDenied
    elenco = list(documenti_per(dip).select_related('dipendente'))
    letture = {l.documento_id: l for l in LetturaDocumento.objects.filter(dipendente=dip, documento__in=elenco)}
    for d in elenco:
        d.lettura = letture.get(d.pk)
        d.manca_visione = d.chiedi_presa_visione and not (d.lettura and d.lettura.presa_visione_il)
    personali = [d for d in elenco if not d.aziendale]
    aziendali = [d for d in elenco if d.aziendale]
    return render(request, 'turni/documenti.html', {
        'personali': personali,
        'aziendali': aziendali,
        'whistleblowing_url': WHISTLEBLOWING_URL,
    })


@login_required
def documento_file(request, documento_id):
    doc = get_object_or_404(Documento, pk=documento_id)
    dip = dipendente_di(request)
    if not (request.user.is_staff or doc.aziendale or (dip and doc.dipendente_id == dip.pk)):
        raise PermissionDenied
    if dip and (doc.aziendale or doc.dipendente_id == dip.pk):
        LetturaDocumento.objects.get_or_create(documento=doc, dipendente=dip)
    return FileResponse(doc.file.open('rb'), filename=doc.nome_file)


@login_required
@require_POST
def presa_visione_documento(request, documento_id):
    doc = get_object_or_404(Documento, pk=documento_id)
    dip = dipendente_di(request)
    if not dip or not (doc.aziendale or doc.dipendente_id == dip.pk):
        raise PermissionDenied
    lettura, _ = LetturaDocumento.objects.get_or_create(documento=doc, dipendente=dip)
    if not lettura.presa_visione_il:
        lettura.presa_visione_il = timezone.now()
        lettura.save(update_fields=['presa_visione_il'])
    messages.success(request, f'Presa visione di «{doc.titolo}» registrata.')
    return redirect('turni:documenti')


# ---------------------------------------------------------------- ufficio


@staff_member_required
def ufficio_documenti(request):
    attivi = list(Dipendente.objects.filter(attivo=True).order_by('nome'))
    if request.method == 'POST':
        if request.POST.get('azione') == 'elimina':
            doc = get_object_or_404(Documento, pk=request.POST.get('documento'))
            doc.file.delete(save=False)
            doc.delete()
            messages.success(request, f'«{doc.titolo}» eliminato.')
            return redirect(_torna(request))
        return _carica(request, attivi)
    elenco = (
        Documento.objects.select_related('dipendente')
        .annotate(
            n_aperti=Count('letture', distinct=True),
            n_visti=Count('letture', filter=Q(letture__presa_visione_il__isnull=False), distinct=True),
        )[:60]
    )
    return render(request, 'turni/ufficio_documenti.html', {
        'elenco': elenco,
        'dipendenti': attivi,
        'n_attivi': sum(1 for d in attivi if d.utente_id),
        'categorie': Documento.Categoria.choices,
    })


def _carica(request, attivi):
    file = request.FILES.getlist('file')
    categoria = request.POST.get('categoria')
    destinatario = request.POST.get('destinatario', '')
    titolo = ' '.join((request.POST.get('titolo') or '').split())[:150]
    chiedi = bool(request.POST.get('chiedi_presa_visione'))
    if categoria not in Documento.Categoria.values or not file:
        messages.error(request, 'Scegli il tipo di documento e almeno un file.')
        return redirect('turni:ufficio_documenti')
    errori = [e for e in map(_file_valido, file) if e]
    if errori:
        for e in errori:
            messages.error(request, e)
        return redirect('turni:ufficio_documenti')

    # (file, dipendente o None per tutti)
    if destinatario == 'auto':
        coppie, senza = [], []
        for f in file:
            d = dipendente_dal_nome_file(f.name, attivi)
            (coppie.append((f, d)) if d else senza.append(f.name))
        if senza:
            messages.error(request, 'Non ho riconosciuto il dipendente in: ' + ', '.join(senza) + '. Nessun file caricato: rinominali con cognome e nome.')
            return redirect('turni:ufficio_documenti')
    elif destinatario == 'tutti':
        coppie = [(f, None) for f in file]
    else:
        dip = get_object_or_404(Dipendente, pk=destinatario or 0)
        coppie = [(f, dip) for f in file]

    nomi = dict(Documento.Categoria.choices)
    creati = []
    for f, dip in coppie:
        creati.append(Documento.objects.create(
            titolo=titolo or (nomi[categoria] if len(coppie) > 1 else Path(f.name).stem.replace('_', ' ')),
            categoria=categoria,
            dipendente=dip,
            file=f,
            nome_file=Path(f.name).name[:200],
            chiedi_presa_visione=chiedi,
            caricato_da=request.user,
        ))
    _avvisa(creati)
    messages.success(request, f'{len(creati)} document{"o caricato" if len(creati) == 1 else "i caricati"}, con avviso sul telefono.')
    return redirect(_torna(request))


def _data(valore):
    try:
        return date.fromisoformat(valore) if valore else None
    except ValueError:
        return None


@staff_member_required
def scheda_dipendente(request, dipendente_id):
    dip = get_object_or_404(Dipendente, pk=dipendente_id)
    if request.method == 'POST':
        azione = request.POST.get('azione')
        if azione == 'anagrafica':
            dip.qualifica = request.POST.get('qualifica', '').strip()[:150]
            dip.telefono = request.POST.get('telefono', '').strip()[:30]
            dip.email = request.POST.get('email', '').strip()[:254]
            tipo = request.POST.get('tipo_contratto', '')
            dip.tipo_contratto = tipo if tipo in TipoContratto.values else ''
            dip.livello = request.POST.get('livello', '').strip()[:40]
            dip.data_assunzione = _data(request.POST.get('data_assunzione'))
            dip.scadenza_contratto = _data(request.POST.get('scadenza_contratto'))
            if dip.email and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', dip.email):
                messages.error(request, 'Email non valida.')
            else:
                dip.save()
                messages.success(request, 'Scheda salvata.')
        elif azione == 'scadenza':
            tipo, quando = request.POST.get('tipo'), _data(request.POST.get('scade_il'))
            if tipo in Scadenza.Tipo.values and quando:
                Scadenza.objects.create(dipendente=dip, tipo=tipo, scade_il=quando, descrizione=request.POST.get('descrizione', '').strip()[:150])
                messages.success(request, 'Scadenza aggiunta.')
            else:
                messages.error(request, 'Scegli il tipo e la data.')
        elif azione == 'togli_scadenza':
            Scadenza.objects.filter(dipendente=dip, pk=request.POST.get('scadenza')).delete()
        return redirect('turni:scheda_dipendente', dipendente_id=dip.pk)
    return render(request, 'turni/scheda_dipendente.html', {
        'd': dip,
        'contratti': TipoContratto.choices,
        'tipi_scadenza': Scadenza.Tipo.choices,
        'categorie': Documento.Categoria.choices,
        'documenti': dip.documenti.prefetch_related('letture'),
        'oggi': timezone.localdate(),
    })
