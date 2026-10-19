"""Regole della manutenzione: chi fa cosa, notifiche, manutenzioni programmate.

Percorso di un guasto (come nei software CMMS, ma snello):
  segnalato (chiunque, con foto) → approvato dal capo turno o dal responsabile manutenzione
  e assegnato al manutentore di turno → in lavorazione → (attesa pezzi) → riparato (con foto).
I pezzi da ordinare li chiede il manutentore o il responsabile; il responsabile approva,
gli acquisti ordinano, all'arrivo la scorta di magazzino sale da sola.
"""

import os
from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image, ImageOps

from . import push
from .models import (
    Comunicazione, Dipendente, EventoIntervento, FermoImpianto, FotoComunicazione, FotoIntervento, Intervento, ManutenzioneProgrammata, Mansione, OrdineRicambio, Turno,
)
from .pulizie import MAX_FOTO

# ---------------------------------------------------------------- chi può fare cosa


def dipendente_di(utente):
    return getattr(utente, 'dipendente', None)


def e_resp(utente):
    dip = dipendente_di(utente)
    return utente.is_superuser or bool(dip and dip.resp_manutenzione)


def e_manutentore(utente):
    dip = dipendente_di(utente)
    return bool(dip and Mansione.MANUTENTORE in dip.mansioni)


def e_capoturno_oggi(utente):
    from .views import e_capoturno

    return e_capoturno(utente, timezone.localdate())


def puo_approvare(utente):
    return e_resp(utente) or e_capoturno_oggi(utente)


def puo_chiedere_pezzi(utente):
    return e_resp(utente) or e_manutentore(utente)


def puo_ordinare(utente):
    """Segna come ordinato / arrivato: responsabile, acquisti, ufficio."""
    dip = dipendente_di(utente)
    return e_resp(utente) or utente.is_staff or bool(dip and dip.acquisti)


def puo_lavorare(utente, intervento):
    dip = dipendente_di(utente)
    return e_resp(utente) or bool(dip and intervento.assegnata_a_id == dip.pk)


# ---------------------------------------------------------------- persone


def manutentori():
    return [d for d in Dipendente.objects.filter(attivo=True).order_by('nome') if Mansione.MANUTENTORE in d.mansioni]


def manutentori_di_turno(giorno=None):
    """Manutentori che oggi lavorano (prima chi è in turno adesso), poi gli altri."""
    giorno = giorno or timezone.localdate()
    tutti = manutentori()
    turni = {t.dipendente_id: t for t in Turno.objects.filter(data=giorno, dipendente__in=tutti)}
    in_turno = [d for d in tutti if d.pk in turni and turni[d.pk].lavora]
    for d in in_turno:
        d.turno_oggi = turni[d.pk]
    return in_turno, [d for d in tutti if d not in in_turno]


def _utenti(dipendenti):
    return [d.utente_id for d in dipendenti if d.utente_id]


def responsabili():
    return list(get_user_model().objects.filter(is_active=True, dipendente__resp_manutenzione=True).values_list('pk', flat=True))


def capiturno_oggi():
    oggi = timezone.localdate()
    return list(
        Turno.objects.filter(data=oggi, capoturno=True, dipendente__utente__is_active=True)
        .values_list('dipendente__utente_id', flat=True)
    )


def acquisti():
    return list(get_user_model().objects.filter(is_active=True, dipendente__acquisti=True).values_list('pk', flat=True))


# ---------------------------------------------------------------- azioni


def url_intervento(i):
    return reverse('turni:intervento', args=[i.pk])


def evento(intervento, utente, testo, nota=False):
    EventoIntervento.objects.create(intervento=intervento, autore=utente, testo=testo[:500], nota=nota)


def avvisa(utenti, escluso, titolo, testo, url):
    ids = {u for u in utenti if u and (escluso is None or u != escluso.pk)}
    push.invia(ids, titolo, testo, url)


def comprimi_foto(file):
    """Foto ridotta a 1600 px in JPEG (come per le pulizie)."""
    if file.size > MAX_FOTO:
        raise ValueError('foto troppo grande')
    img = ImageOps.exif_transpose(Image.open(file)).convert('RGB')
    img.thumbnail((1600, 1600))
    buf = BytesIO()
    img.save(buf, 'JPEG', quality=75, optimize=True)
    return ContentFile(buf.getvalue(), name='foto.jpg')


def segnala(utente, macchina, descrizione, ferma, foto):
    i = Intervento(
        macchina=macchina, descrizione=descrizione, macchina_ferma=ferma, segnalata_da=utente,
        priorita=Intervento.Priorita.URGENTE if ferma else Intervento.Priorita.NORMALE,
    )
    i.foto_guasto.save('guasto.jpg', comprimi_foto(foto), save=False)
    i.save()
    evento(i, utente, 'Guasto segnalato' + (' · macchina ferma' if ferma else ''))
    avvisa(
        responsabili() + capiturno_oggi(), utente,
        f"{'🔴 Macchina ferma' if ferma else 'Guasto'} · {macchina.nome}", descrizione, url_intervento(i),
    )
    return i


def approva(utente, i, manutentore, priorita=None):
    i.stato = Intervento.Stato.ASSEGNATA
    i.assegnata_a = manutentore
    i.approvata_da, i.approvata_il = utente, timezone.now()
    if priorita:
        i.priorita = priorita
    i.save()
    evento(i, utente, f'Approvato e assegnato a {manutentore.nome_breve}')
    avvisa([manutentore.utente_id], utente, f'Nuovo intervento · {i.macchina.nome}', i.descrizione, url_intervento(i))
    if i.segnalata_da_id:
        avvisa([i.segnalata_da_id], utente, 'Segnalazione presa in carico',
               f'{i.macchina.nome}: se ne occupa {manutentore.nome_breve}', url_intervento(i))


def rifiuta(utente, i, motivo):
    i.stato = Intervento.Stato.RIFIUTATA
    i.motivo_rifiuto = motivo
    i.save()
    evento(i, utente, 'Segnalazione non approvata' + (f': {motivo}' if motivo else ''))
    avvisa([i.segnalata_da_id], utente, 'Segnalazione non approvata', f'{i.macchina.nome}: {motivo}', url_intervento(i))


def inizia(utente, i):
    i.stato = Intervento.Stato.IN_CORSO
    i.iniziata_il = i.iniziata_il or timezone.now()
    i.save()
    evento(i, utente, 'Lavoro iniziato')


MAX_VIDEO = 50 * 1024 * 1024
ESTENSIONI_VIDEO = ('.mp4', '.mov', '.m4v', '.3gp', '.webm')


def controlla_video(f):
    """Solo video veri e non enormi: estensione, tipo dichiarato e dimensione."""
    if f is None:
        return None
    nome = (f.name or '').lower()
    if f.size > MAX_VIDEO or not nome.endswith(ESTENSIONI_VIDEO) or not (f.content_type or '').startswith('video/'):
        raise ValueError('video non valido')
    return f


def dopo_il_lavoro(utente, i, collaboratori, resta_da_fare, video):
    """Colleghi che hanno aiutato, video e, se serve, il prossimo intervento da approvare."""
    if collaboratori:
        i.collaboratori.set(collaboratori)
    if video:
        i.video.save('video' + os.path.splitext(video.name)[1].lower(), video, save=True)
    if resta_da_fare:
        nuovo = Intervento.objects.create(macchina=i.macchina, descrizione=resta_da_fare, segnalata_da=utente)
        evento(nuovo, utente, f'Proposto dopo il lavoro #{i.pk}')
        evento(i, utente, f'Resta da fare: {resta_da_fare} (intervento #{nuovo.pk})')
        avvisa(responsabili() + capiturno_oggi(), utente, f'Da fare · {i.macchina.nome}', resta_da_fare, url_intervento(nuovo))


def completa(utente, i, lavoro, foto, ore, pezzi):
    """pezzi: lista di (ricambio o None, descrizione, quantità). Scala la scorta di magazzino."""
    i.stato = Intervento.Stato.COMPLETATA
    i.completata_il = timezone.now()
    i.completata_da = utente
    i.iniziata_il = i.iniziata_il or i.completata_il
    i.lavoro_svolto = lavoro
    i.ore_lavoro = ore
    i.foto_riparazione.save('riparazione.jpg', comprimi_foto(foto), save=False)
    i.save()
    for ricambio, descrizione, quantita in pezzi:
        i.ricambi_usati.create(ricambio=ricambio, descrizione=descrizione, quantita=quantita)
        if ricambio:
            ricambio.scorta -= quantita
            ricambio.save(update_fields=['scorta'])
    if i.piano_id:
        i.piano.ultima = timezone.localdate()
        i.piano.save(update_fields=['ultima'])
    evento(i, utente, 'Riparato' if i.tipo == Intervento.Tipo.GUASTO else 'Manutenzione fatta')
    avvisa(responsabili() + [i.segnalata_da_id], utente, f'✅ Riparato · {i.macchina.nome}', lavoro, url_intervento(i))


def chiedi_pezzo(utente, ricambio, descrizione, quantita, urgente, nota, intervento=None, macchina=None, foto=None):
    o = OrdineRicambio(
        intervento=intervento, macchina=macchina or (intervento.macchina if intervento else None),
        ricambio=ricambio, descrizione=descrizione, quantita=quantita, urgente=urgente, nota=nota,
        richiesto_da=utente,
    )
    if foto:
        o.foto.save('pezzo.jpg', comprimi_foto(foto), save=False)
    if e_resp(utente):  # chiesto dal responsabile: già approvato
        o.stato, o.approvato_da = OrdineRicambio.Stato.APPROVATO, utente
    o.save()
    if intervento:
        if intervento.stato in (Intervento.Stato.ASSEGNATA, Intervento.Stato.IN_CORSO):
            intervento.stato = Intervento.Stato.ATTESA_PEZZI
            intervento.save(update_fields=['stato'])
        evento(intervento, utente, f'Chiesto pezzo: {o.nome} × {quantita}')
    if o.stato == OrdineRicambio.Stato.RICHIESTO:
        avvisa(responsabili(), utente, 'Pezzo da approvare', f'{o.nome} × {quantita}', reverse('turni:ordini'))
    else:
        avvisa(acquisti(), utente, 'Pezzo da ordinare', f'{o.nome} × {quantita}', reverse('turni:ordini'))
    return o


def avanza_ordine(utente, o, azione, fornitore='', dove=''):
    if azione == 'approva' and o.stato == OrdineRicambio.Stato.RICHIESTO and e_resp(utente):
        o.stato, o.approvato_da = OrdineRicambio.Stato.APPROVATO, utente
        avvisa(acquisti(), utente, 'Pezzo da ordinare', f'{o.nome} × {o.quantita}', reverse('turni:ordini'))
    elif azione == 'ordinato' and o.stato == OrdineRicambio.Stato.APPROVATO and puo_ordinare(utente):
        o.stato, o.ordinato_il, o.fornitore = OrdineRicambio.Stato.ORDINATO, timezone.now(), fornitore[:80]
    elif azione == 'arrivato' and o.stato == OrdineRicambio.Stato.ORDINATO and (puo_ordinare(utente) or e_manutentore(utente)):
        o.stato, o.arrivato_il, o.dove = OrdineRicambio.Stato.ARRIVATO, timezone.now(), dove[:80]
        if o.ricambio:
            o.ricambio.scorta += o.quantita
            o.ricambio.save(update_fields=['scorta'])
        i = o.intervento
        if i:
            evento(i, utente, f'Arrivato: {o.nome}' + (f' · si trova {o.dove}' if o.dove else ''))
            if i.stato == Intervento.Stato.ATTESA_PEZZI and not i.ordini.exclude(pk=o.pk).filter(
                stato__in=[OrdineRicambio.Stato.RICHIESTO, OrdineRicambio.Stato.APPROVATO, OrdineRicambio.Stato.ORDINATO]
            ).exists():
                i.stato = Intervento.Stato.IN_CORSO
                i.save(update_fields=['stato'])
            avvisa([i.assegnata_a.utente_id if i.assegnata_a else None] + responsabili(), utente,
                   f'📦 Arrivato il pezzo · {i.macchina.nome}', o.nome + (f' · si trova {o.dove}' if o.dove else ''), url_intervento(i))
    elif azione == 'annulla' and o.aperto and (e_resp(utente) or o.richiesto_da_id == utente.pk):
        o.stato = OrdineRicambio.Stato.ANNULLATO
    else:
        return False
    o.save()
    return True


def genera_programmate(giorno=None):
    """Le programmate scadute diventano interventi da assegnare (una sola aperta per piano)."""
    giorno = giorno or timezone.localdate()
    nuovi = []
    aperti = Intervento.objects.filter(stato__in=Intervento.APERTI, piano__isnull=False).values_list('piano_id', flat=True)
    for p in ManutenzioneProgrammata.objects.filter(attiva=True, macchina__attiva=True).exclude(pk__in=aperti).select_related('macchina'):
        if p.prossima <= giorno:
            testo = p.attivita + (('\n' + '\n'.join(f'• {r}' for r in p.righe_istruzioni)) if p.istruzioni else '')
            i = Intervento.objects.create(
                macchina=p.macchina, tipo=Intervento.Tipo.PROGRAMMATA, piano=p, descrizione=testo,
                priorita=Intervento.Priorita.NORMALE,
            )
            evento(i, None, f'Manutenzione programmata in scadenza (ogni {p.ogni_giorni} giorni)')
            nuovi.append(i)
    return nuovi


def stato_macchine(macchine):
    """Aggiunge a ogni macchina: stato (ok / problemi / ferma) e interventi aperti."""
    aperti = {}
    for i in Intervento.objects.filter(stato__in=Intervento.APERTI, macchina__in=macchine, tipo=Intervento.Tipo.GUASTO):
        aperti.setdefault(i.macchina_id, []).append(i)
    for m in macchine:
        lista = aperti.get(m.pk, [])
        m.aperti = len(lista)
        fuori = indisponibili_ora().get(m.pk)
        if fuori:
            m.stato, m.stato_testo = 'ferma', f"Ferma fino a {timezone.localtime(fuori.al):%d/%m %H:%M}"
        elif any(i.macchina_ferma for i in lista):
            m.stato, m.stato_testo = 'ferma', 'Ferma'
        elif lista:
            m.stato, m.stato_testo = 'problemi', 'Guasto aperto'
        else:
            m.stato, m.stato_testo = 'ok', 'In funzione'
    return macchine


def statistiche(macchina):
    da = timezone.now() - timedelta(days=365)
    guasti = macchina.interventi.filter(tipo=Intervento.Tipo.GUASTO, segnalata_il__gte=da).exclude(stato=Intervento.Stato.RIFIUTATA)
    riparati = [i for i in guasti if i.completata_il]
    ore_riparazione = [(i.completata_il - i.segnalata_il).total_seconds() / 3600 for i in riparati]
    return {
        'guasti': guasti.count(),
        'ore_fermo': round(sum(i.ore_fermo for i in guasti), 1),
        'tempo_medio': round(sum(ore_riparazione) / len(ore_riparazione), 1) if ore_riparazione else None,
    }


def da_fare_per(utente):
    """Numero per il pallino della barra: cose che aspettano questa persona."""
    n = 0
    if puo_approvare(utente):
        n += Intervento.objects.filter(stato=Intervento.Stato.SEGNALATA).count()
    dip = dipendente_di(utente)
    if dip:
        n += Intervento.objects.filter(assegnata_a=dip, stato__in=[Intervento.Stato.ASSEGNATA]).count()
    if e_resp(utente):
        n += OrdineRicambio.objects.filter(stato=OrdineRicambio.Stato.RICHIESTO).count()
    if puo_ordinare(utente) and dip and dip.acquisti:
        n += OrdineRicambio.objects.filter(stato=OrdineRicambio.Stato.APPROVATO).count()
    return n



# ---------------------------------------------------------------- fermo impianto


def chi_avvisare_fermo():
    in_turno, _ = manutentori_di_turno()
    return responsabili() + capiturno_oggi() + [d.utente_id for d in in_turno]


def puo_far_ripartire(utente, fermo):
    # chi è in impianto vede ripartire le macchine: può segnarlo chiunque, resta scritto chi l'ha fatto
    return utente.is_authenticated


def segnala_fermo(utente, impianto, causa, macchina, descrizione, dal, foto=None):
    f = FermoImpianto(impianto=impianto, causa=causa, macchina=macchina, descrizione=descrizione,
                      fermo_dal=dal, segnalato_da=utente)
    dati = comprimi_foto(foto).read() if foto else None
    if dati:
        f.foto.save('fermo.jpg', ContentFile(dati), save=False)
    if macchina:
        # la macchina che ha fermato l'impianto diventa subito un intervento urgente per la manutenzione
        i = Intervento.objects.create(
            macchina=macchina, descrizione=f'Fermo {f.get_impianto_display()}: {f.get_causa_display()}'
            + (f'. {descrizione}' if descrizione else ''),
            macchina_ferma=True, priorita=Intervento.Priorita.URGENTE, segnalata_da=utente, segnalata_il=dal,
        )
        if dati:
            i.foto_guasto.save('guasto.jpg', ContentFile(dati), save=True)
        evento(i, utente, f'Guasto segnalato con il fermo di {f.get_impianto_display()}')
        f.intervento = i
    f.save()
    avvisa(chi_avvisare_fermo(), utente, f'⛔ {f.get_impianto_display()} fermo',
           f.get_causa_display() + (f' · {macchina.nome}' if macchina else '') + (f': {descrizione}' if descrizione else ''),
           reverse('turni:fermo', args=[f.pk]))
    return f


def fai_ripartire(utente, f, quando, sistemazione, foto=None):
    f.ripartito_il = quando
    f.ripartenza_da = utente
    f.sistemazione = sistemazione
    if foto:
        f.foto_ripartenza.save('ripartenza.jpg', comprimi_foto(foto), save=False)
    f.save()
    if f.intervento_id:
        evento(f.intervento, utente, f'{f.get_impianto_display()} ripartito dopo {f.durata}' + (f': {sistemazione}' if sistemazione else ''))
    avvisa(chi_avvisare_fermo() + [f.segnalato_da_id], utente, f'✅ {f.get_impianto_display()} ripartito',
           f'Fermo durato {f.durata}' + (f' · {sistemazione}' if sistemazione else ''), reverse('turni:fermo', args=[f.pk]))


# ---------------------------------------------------------------- lavoro fatto senza segnalazione

MAX_FOTO_LAVORO = 12


def puo_registrare_lavoro(utente):
    return e_resp(utente) or e_manutentore(utente) or e_capoturno_oggi(utente)


def registra_lavoro(utente, macchina, testo, foto, ore, pezzi, tipo_lavoro='', pezzo=''):
    """Ripristino o sostituzione già fatti: si registrano direttamente come intervento chiuso, con le foto."""
    adesso = timezone.now()
    dip = dipendente_di(utente)
    i = Intervento(
        macchina=macchina, tipo=Intervento.Tipo.LAVORO, descrizione=testo, lavoro_svolto=testo,
        stato=Intervento.Stato.COMPLETATA, segnalata_da=utente, segnalata_il=adesso, iniziata_il=adesso,
        completata_il=adesso, completata_da=utente, assegnata_a=dip, ore_lavoro=ore,
        tipo_lavoro=tipo_lavoro, pezzo=pezzo,
    )
    compresse = [comprimi_foto(f) for f in foto[:MAX_FOTO_LAVORO]]
    i.foto_riparazione.save('lavoro.jpg', compresse[0], save=False)
    i.save()
    for c in compresse[1:]:
        FotoIntervento.objects.create(intervento=i, foto=c)
    for ricambio, descrizione, quantita in pezzi:
        i.ricambi_usati.create(ricambio=ricambio, descrizione=descrizione, quantita=quantita)
        if ricambio:
            ricambio.scorta -= quantita
            ricambio.save(update_fields=['scorta'])
    evento(i, utente, 'Manutenzione registrata')
    avvisa(responsabili(), utente, f'✅ {macchina.nome}', testo, url_intervento(i))
    return i


# ---------------------------------------------------------------- comunicazioni del responsabile


def puo_comunicare(utente):
    from .views_messaggi import e_direzione

    return e_resp(utente) or e_direzione(utente) or utente.is_staff or e_manutentore(utente) or e_capoturno_oggi(utente)


def puo_chiudere(utente, c):
    return e_resp(utente) or utente.is_staff or c.autore_id == utente.pk or c.in_gestione_da_id == utente.pk


def destinatari_di(c):
    User = get_user_model()
    attivi = User.objects.filter(is_active=True)
    if c.destinatari == Comunicazione.A.CAPITURNO:
        ids = capiturno_oggi() + responsabili()
    elif c.destinatari == Comunicazione.A.MANUTENTORI:
        ids = [d.utente_id for d in manutentori()] + responsabili()
    elif c.destinatari == Comunicazione.A.PALISTI:
        ids = [d.utente_id for d in Dipendente.objects.filter(attivo=True, mansione__contains=Mansione.PALISTA)] + responsabili()
    else:
        ids = list(attivi.values_list('pk', flat=True))
    return [i for i in ids if i]


def indisponibili_ora():
    adesso = timezone.now()
    return {c.macchina_id: c for c in Comunicazione.objects.filter(
        tipo=Comunicazione.Tipo.INDISPONIBILE, macchina__isnull=False, dal__lte=adesso, al__gte=adesso
    ).exclude(stato=Comunicazione.Stato.RISOLTA)}


def avvisi_per(utente):
    """Mezzi e macchine non disponibili (da ora o in arrivo nelle prossime 48 ore) che questa persona deve sapere."""
    adesso = timezone.now()
    qs = Comunicazione.objects.filter(tipo__in=[Comunicazione.Tipo.INDISPONIBILE, Comunicazione.Tipo.FERMO], al__gte=adesso,
                                      dal__lte=adesso + timedelta(hours=48)).exclude(stato=Comunicazione.Stato.RISOLTA).select_related('macchina')
    return [c for c in qs if utente.pk in destinatari_di(c)]


ORE_FASCIA = {'1T': (6, 8), '2T': (14, 8), 'N': (22, 8)}  # inizio e durata in ore


def periodo_fermo(giorno, fascia):
    """Inizio e fine di un fermo programmato: giornata intera o un turno."""
    from datetime import datetime, time

    if fascia in ORE_FASCIA:
        ora, durata = ORE_FASCIA[fascia]
        inizio = timezone.make_aware(datetime.combine(giorno, time(ora)))
        return inizio, inizio + timedelta(hours=durata)
    inizio = timezone.make_aware(datetime.combine(giorno, time(0)))
    return inizio, inizio + timedelta(days=1)


def crea_comunicazione(utente, tipo, testo, luogo, fascia, macchina, dal, al, destinatari, foto, motivo='', urgente=False, valore='', video=None):
    c = Comunicazione.objects.create(tipo=tipo, testo=testo, luogo=luogo, fascia=fascia, macchina=macchina,
                                     dal=dal, al=al, destinatari=destinatari, autore=utente, motivo=motivo,
                                     urgente=urgente, valore=valore)
    for f in foto[:MAX_FOTO_LAVORO]:
        FotoComunicazione.objects.create(comunicazione=c, foto=comprimi_foto(f))
    if video:
        c.video.save('video' + os.path.splitext(video.name)[1].lower(), video, save=True)
    titolo = f'{c.icona} {c.get_tipo_display()}' + (f' · {macchina.nome}' if macchina else (f' · {c.get_luogo_display()}' if luogo else ''))
    if c.tipo == Comunicazione.Tipo.FERMO:
        titolo = f'🛑 {c.get_luogo_display()} fermo: {c.periodo}'
    if c.urgente:
        titolo = '⚠️ URGENTE · ' + titolo
    avvisa(destinatari_di(c), utente, titolo, testo, reverse('turni:comunicazione', args=[c.pk]))
    return c


def rispondi(utente, c, testo, azione):
    if azione == 'gestione' and c.stato == Comunicazione.Stato.APERTA:
        c.stato, c.in_gestione_da = Comunicazione.Stato.IN_GESTIONE, utente
        c.save(update_fields=['stato', 'in_gestione_da'])
        testo = testo or 'Me ne occupo'
    elif azione == 'risolta' and c.stato != Comunicazione.Stato.RISOLTA and puo_chiudere(utente, c):
        c.stato, c.risolta_da, c.risolta_il = Comunicazione.Stato.RISOLTA, utente, timezone.now()
        c.save(update_fields=['stato', 'risolta_da', 'risolta_il'])
        testo = testo or 'Risolta'
    if testo:
        c.risposte.create(autore=utente, testo=testo[:500])
        avvisa([c.autore_id, c.in_gestione_da_id], utente, f'💬 {c.get_tipo_display()}', testo, reverse('turni:comunicazione', args=[c.pk]))
