"""Funzioni HR dell'ufficio (Giulia, 11/11/2026): Scadenze del personale e Documenti con presa visione."""

import os
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from . import push
from .models import Dipendente, Documento, PresaVisione, Scadenza


def _solo_ufficio(request):
    if not request.user.is_staff:
        raise PermissionDenied


# ---------------------------------------------------------------- scadenze


def scadenze_vicine():
    """Le scadenze aperte già passate o dentro il preavviso."""
    limite = timezone.localdate() + timedelta(days=365)  # il preavviso massimo
    aperte = (Scadenza.objects.filter(chiusa_il__isnull=True, dipendente__attivo=True, scade_il__lte=limite)
              .select_related('dipendente').order_by('scade_il'))
    return [s for s in aperte if s.stato != 'ok']


def _data(valore):
    try:
        return date.fromisoformat(valore or '')
    except ValueError:
        return None


@login_required
def scadenze(request):
    _solo_ufficio(request)
    if request.method == 'POST':
        azione = request.POST.get('azione')
        if azione == 'aggiungi':
            dip = Dipendente.objects.filter(pk=request.POST.get('dipendente') or 0, attivo=True).first()
            tipo = request.POST.get('tipo')
            quando = _data(request.POST.get('scade_il'))
            try:
                preavviso = max(1, min(365, int(request.POST.get('preavviso') or 30)))
            except ValueError:
                preavviso = 30
            if not dip or tipo not in Scadenza.Tipo.values or not quando:
                messages.error(request, 'Scegli il dipendente, il tipo e la data di scadenza.')
            else:
                Scadenza.objects.create(dipendente=dip, tipo=tipo, scade_il=quando, preavviso_giorni=preavviso,
                                        descrizione=(request.POST.get('descrizione') or '').strip()[:120],
                                        note=(request.POST.get('note') or '').strip()[:300], creata_da=request.user)
                messages.success(request, f'Scadenza aggiunta per {dip.nome_breve}.')
        elif azione in ('rinnova', 'chiudi'):
            s = get_object_or_404(Scadenza, pk=request.POST.get('scadenza'), chiusa_il__isnull=True)
            if azione == 'rinnova':
                nuova = _data(request.POST.get('nuova'))
                if not nuova or nuova <= s.scade_il:
                    messages.error(request, 'La nuova scadenza deve venire dopo quella attuale.')
                else:
                    s.scade_il = nuova
                    s.save(update_fields=['scade_il'])
                    messages.success(request, f'{s.get_tipo_display()} di {s.dipendente.nome_breve} rinnovata al {nuova:%d/%m/%Y}.')
            else:
                s.chiusa_il = timezone.now()
                s.save(update_fields=['chiusa_il'])
                messages.success(request, 'Scadenza chiusa: non comparirà più negli avvisi.')
        return redirect(request.get_full_path())

    tipo = request.GET.get('tipo') if request.GET.get('tipo') in Scadenza.Tipo.values else ''
    q = (request.GET.get('q') or '').strip()
    elenco = Scadenza.objects.filter(chiusa_il__isnull=True, dipendente__attivo=True).select_related('dipendente')
    if tipo:
        elenco = elenco.filter(tipo=tipo)
    if q:
        elenco = elenco.filter(dipendente__nome__icontains=q)
    elenco = list(elenco.order_by('scade_il'))
    return render(request, 'turni/hr_scadenze.html', {
        'elenco': elenco, 'tipi': Scadenza.Tipo.choices, 'tipo': tipo, 'q': q,
        'dipendenti': Dipendente.objects.filter(attivo=True).order_by('nome'),
        'conta': {k: sum(1 for s in elenco if s.stato == k) for k in ('scaduta', 'vicina', 'ok')},
        'oggi': timezone.localdate(),
    })


# ---------------------------------------------------------------- documenti

ESTENSIONI = {'.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
MAX_DOCUMENTO = 10 * 1024 * 1024


def _file_valido(f):
    est = os.path.splitext(f.name)[1].lower()
    if est not in ESTENSIONI:
        return 'Carica un PDF o una foto (JPG, PNG).'
    if f.size > MAX_DOCUMENTO:
        return 'Il file è troppo grande (massimo 10 MB).'
    inizio = f.read(8)
    f.seek(0)
    firme = {'.pdf': (b'%PDF',), '.png': (b'\x89PNG',), '.jpg': (b'\xff\xd8',), '.jpeg': (b'\xff\xd8',)}
    if not inizio.startswith(firme[est]):
        return 'Il file non sembra un PDF o una foto valida.'
    return ''


def documenti_per(dip):
    """I documenti che vede una persona: i suoi e quelli per tutti."""
    return Documento.objects.filter(Q(dipendente=dip) | Q(dipendente__isnull=True))


def da_leggere(dip):
    """Documenti con presa visione richiesta che la persona non ha ancora confermato."""
    if dip is None:
        return []
    return list(documenti_per(dip).filter(presa_visione=True, caricato_il__gte=_dal_assunto(dip))
                .exclude(prese_visione__dipendente=dip))


def _dal_assunto(dip):
    # i documenti "per tutti" caricati prima che la persona avesse l'accesso non le si chiedono
    return getattr(dip.utente, 'date_joined', None) or timezone.now() - timedelta(days=3650)


@login_required
def documenti_ufficio(request):
    _solo_ufficio(request)
    if request.method == 'POST':
        f = request.FILES.get('file')
        titolo = (request.POST.get('titolo') or '').strip()[:120]
        tipo = request.POST.get('tipo')
        a_chi = request.POST.get('a_chi') or ''
        dip = Dipendente.objects.filter(pk=a_chi, attivo=True).first() if a_chi.isdigit() else None
        errore = ''
        if not f:
            errore = 'Scegli il file da caricare.'
        elif not titolo or tipo not in Documento.Tipo.values:
            errore = 'Scrivi il titolo e scegli il tipo di documento.'
        elif a_chi != 'tutti' and dip is None:
            errore = 'Scegli a chi è destinato: a tutti o a un dipendente.'
        elif tipo == Documento.Tipo.BUSTA and dip is None:
            errore = 'La busta paga va a un solo dipendente.'
        else:
            errore = _file_valido(f)
        if errore:
            messages.error(request, errore)
        else:
            d = Documento.objects.create(titolo=titolo, tipo=tipo, file=f, nome_file=os.path.basename(f.name)[:150],
                                         dipendente=dip, presa_visione=bool(request.POST.get('presa_visione')),
                                         caricato_da=request.user)
            destinatari = [dip.utente_id] if dip else list(
                Dipendente.objects.filter(attivo=True, utente__isnull=False).values_list('utente_id', flat=True))
            push.invia(destinatari, f'Nuovo documento: {titolo}',
                       'Da leggere e confermare' if d.presa_visione else d.get_tipo_display(),
                       reverse('turni:documenti'), mittente=request.user, tipo='documento', oggetto_id=d.pk)
            messages.success(request, f'Documento caricato e inviato a {dip.nome_breve if dip else "tutti"}.')
        return redirect('turni:documenti_ufficio')
    tutti = Dipendente.objects.filter(attivo=True, utente__isnull=False).count()
    elenco = list(Documento.objects.select_related('dipendente').annotate(letti=Count('prese_visione'))[:100])
    for d in elenco:
        d.su = 1 if d.dipendente_id else tutti
    return render(request, 'turni/hr_documenti.html', {
        'elenco': elenco, 'tipi': Documento.Tipo.choices,
        'dipendenti': Dipendente.objects.filter(attivo=True, utente__isnull=False).order_by('nome'),
    })


@login_required
def documento_ufficio(request, pk):
    """Chi ha letto e chi no."""
    _solo_ufficio(request)
    d = get_object_or_404(Documento.objects.select_related('dipendente'), pk=pk)
    persone = [d.dipendente] if d.dipendente else list(Dipendente.objects.filter(attivo=True, utente__isnull=False).order_by('nome'))
    letti = {p.dipendente_id: p.il for p in d.prese_visione.all()}
    righe = [(p, letti.get(p.pk)) for p in persone]
    return render(request, 'turni/hr_documento.html', {'d': d, 'righe': righe, 'n_letti': len(letti)})


@login_required
def documento_file(request, pk):
    d = get_object_or_404(Documento, pk=pk)
    dip = getattr(request.user, 'dipendente', None)
    if not (request.user.is_staff or (dip and (d.dipendente_id is None or d.dipendente_id == dip.pk))):
        raise PermissionDenied
    est = os.path.splitext(d.file.name)[1].lower()
    try:
        apri = d.file.open('rb')
    except (FileNotFoundError, OSError):
        raise Http404
    return FileResponse(apri, content_type=ESTENSIONI.get(est, 'application/octet-stream'),
                        filename=d.nome_file or f'documento{est}', as_attachment=False)


@login_required
def documenti(request):
    """I documenti del dipendente: i suoi e quelli per tutti, con «Ho letto»."""
    dip = getattr(request.user, 'dipendente', None)
    if dip is None:
        return redirect('turni:documenti_ufficio') if request.user.is_staff else redirect('turni:home')
    if request.method == 'POST':
        d = get_object_or_404(documenti_per(dip), pk=request.POST.get('documento'))
        PresaVisione.objects.get_or_create(documento=d, dipendente=dip)
        from .models import Notifica
        Notifica.objects.filter(utente=request.user, tipo='documento', oggetto_id=d.pk).update(esito='confermata')
        messages.success(request, f'Presa visione confermata: {d.titolo}.')
        return redirect(request.POST.get('dopo') if request.POST.get('dopo') in (reverse('turni:miei_turni'),) else 'turni:documenti')
    elenco = list(documenti_per(dip).select_related('dipendente'))
    letti = set(PresaVisione.objects.filter(dipendente=dip).values_list('documento_id', flat=True))
    for d in elenco:
        d.letto = d.pk in letti
    return render(request, 'turni/hr_documenti_miei.html', {'elenco': elenco})
