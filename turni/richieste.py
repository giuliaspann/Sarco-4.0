"""Cambi turno, ferie e turni extra: controlli e applicazione ai turni."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import CambioTurno, Fascia, Pulizia, RichiestaFerie, Turno

CAMPI_TURNO = ('fascia', 'postazione', 'capoturno', 'codice')


class RichiestaNonValida(Exception):
    pass


def e_responsabile(user):
    return user.is_authenticated and user.has_perm('turni.approva_richieste')


def _chiave(turno):
    return f'{turno.dipendente_id}|{turno.data.isoformat()}'


def _stato_turno(turno):
    return [getattr(turno, c) for c in CAMPI_TURNO]


def turni_coinvolti(richiedente, collega, giorni):
    """{(dipendente_id, giorno): Turno} per i due colleghi nei giorni del cambio."""
    turni = Turno.objects.filter(dipendente__in=[richiedente, collega], data__in=giorni).select_related('dipendente')
    return {(t.dipendente_id, t.data): t for t in turni}


def anteprima(richiedente, collega, giorni):
    """Per ogni giorno: turno attuale e turno dopo il cambio, per entrambi."""
    turni = turni_coinvolti(richiedente, collega, giorni)
    righe = []
    for g in giorni:
        a, b = turni.get((richiedente.pk, g)), turni.get((collega.pk, g))
        if a is None or b is None:
            raise RichiestaNonValida(f'Per il {g:%d/%m} i turni non sono ancora pubblicati.')
        righe.append({'giorno': g, 'io_prima': a, 'collega_prima': b})
    return righe, turni


def crea_cambio(richiedente, collega, giorno1, giorno2=None, motivo=''):
    oggi = timezone.localdate()
    giorni = [g for g in (giorno1, giorno2) if g]
    if collega == richiedente:
        raise RichiestaNonValida('Scegli un collega.')
    if any(g <= oggi for g in giorni):
        raise RichiestaNonValida('Si possono cambiare solo i turni da domani in poi.')
    if giorno2 and giorno2 == giorno1:
        raise RichiestaNonValida('Il giorno di recupero deve essere diverso.')
    righe, turni = anteprima(richiedente, collega, giorni)
    if all(_stato_turno(r['io_prima']) == _stato_turno(r['collega_prima']) for r in righe):
        raise RichiestaNonValida('Avete lo stesso turno: non c\'è niente da scambiare.')
    aperti = CambioTurno.objects.filter(stato__in=CambioTurno.IN_CORSO).filter(
        Q(richiedente__in=[richiedente, collega]) | Q(collega__in=[richiedente, collega])
    ).filter(Q(giorno1__in=giorni) | Q(giorno2__in=giorni))
    if aperti.exists():
        raise RichiestaNonValida('C\'è già una richiesta di cambio aperta per questi giorni.')
    return CambioTurno.objects.create(
        richiedente=richiedente,
        collega=collega,
        giorno1=giorno1,
        giorno2=giorno2,
        motivo=motivo[:300],
        situazione={_chiave(t): _stato_turno(t) for t in turni.values()},
    )


def risposta_collega(cambio, accetta):
    if cambio.stato != CambioTurno.Stato.ATTESA_COLLEGA:
        raise RichiestaNonValida('Questa richiesta non aspetta più la tua risposta.')
    if accetta and cambio.scaduto:
        raise RichiestaNonValida('Il giorno del cambio è già arrivato.')
    cambio.stato = CambioTurno.Stato.ATTESA_UFFICIO if accetta else CambioTurno.Stato.RIFIUTATO_COLLEGA
    cambio.risposta_collega_il = timezone.now()
    cambio.save()


def _togli_pulizie_da_fare(turno):
    turno.pulizie.filter(stato=Pulizia.Stato.DA_FARE, aggiunta_da_operaio=False).delete()


def decisione_ufficio_cambio(cambio, utente, approva, nota=''):
    if cambio.stato != CambioTurno.Stato.ATTESA_UFFICIO:
        raise RichiestaNonValida('Questa richiesta non è in attesa di approvazione.')
    with transaction.atomic():
        if approva:
            if cambio.scaduto:
                raise RichiestaNonValida('Il giorno del cambio è già passato.')
            turni = turni_coinvolti(cambio.richiedente, cambio.collega, cambio.giorni)
            attuale = {_chiave(t): _stato_turno(t) for t in turni.values()}
            if attuale != cambio.situazione:
                raise RichiestaNonValida(
                    'Nel frattempo i turni di questi giorni sono cambiati: rifiuta e fai rifare la richiesta.'
                )
            for g in cambio.giorni:
                a, b = turni[(cambio.richiedente_id, g)], turni[(cambio.collega_id, g)]
                for campo in CAMPI_TURNO:
                    va, vb = getattr(a, campo), getattr(b, campo)
                    setattr(a, campo, vb)
                    setattr(b, campo, va)
                a.nota_modifica = f'Cambio con {cambio.collega.nome_breve}'
                b.nota_modifica = f'Cambio con {cambio.richiedente.nome_breve}'
                for t in (a, b):
                    t.save()
                    _togli_pulizie_da_fare(t)
        cambio.stato = CambioTurno.Stato.APPROVATO if approva else CambioTurno.Stato.RIFIUTATO_UFFICIO
        cambio.gestito_da = utente
        cambio.gestito_il = timezone.now()
        cambio.nota_ufficio = nota[:300]
        cambio.save()


def crea_ferie(dipendente, tipo, dal, al, motivo=''):
    if al < dal:
        raise RichiestaNonValida('La data di fine è prima di quella di inizio.')
    if dal < timezone.localdate():
        raise RichiestaNonValida('Non si possono chiedere ferie per giorni già passati.')
    if (al - dal).days > 60:
        raise RichiestaNonValida('Massimo 60 giorni per richiesta: dividila in più richieste.')
    sovrapposte = dipendente.richieste_ferie.filter(
        stato__in=[RichiestaFerie.Stato.ATTESA, RichiestaFerie.Stato.APPROVATA], dal__lte=al, al__gte=dal
    )
    if sovrapposte.exists():
        raise RichiestaNonValida('Hai già una richiesta per alcuni di questi giorni.')
    return RichiestaFerie.objects.create(dipendente=dipendente, tipo=tipo, dal=dal, al=al, motivo=motivo[:300])


def segna_ferie_sui_turni(richiesta, turni):
    for t in turni:
        t.fascia = richiesta.fascia
        t.postazione = ''
        t.capoturno = False
        t.codice = richiesta.get_tipo_display().upper()
        t.nota_modifica = f'{richiesta.get_tipo_display()} approvate dall\'ufficio'
        t.save()
        _togli_pulizie_da_fare(t)


def decisione_ufficio_ferie(richiesta, utente, approva, nota=''):
    if richiesta.stato != RichiestaFerie.Stato.ATTESA:
        raise RichiestaNonValida('Questa richiesta non è in attesa di approvazione.')
    with transaction.atomic():
        richiesta.stato = RichiestaFerie.Stato.APPROVATA if approva else RichiestaFerie.Stato.RIFIUTATA
        richiesta.gestita_da = utente
        richiesta.gestita_il = timezone.now()
        richiesta.nota_ufficio = nota[:300]
        richiesta.save()
        if approva:
            # le settimane non ancora caricate prendono le ferie al momento dell'import
            turni = richiesta.dipendente.turni.filter(data__range=(richiesta.dal, richiesta.al))
            segna_ferie_sui_turni(richiesta, turni)


def ferie_approvate(dipendente, giorno):
    return dipendente.richieste_ferie.filter(stato=RichiestaFerie.Stato.APPROVATA, dal__lte=giorno, al__gte=giorno).first()


# ---------------------------------------------------------------- turni extra (volontari)


def ha_mansione(dipendente, ruolo):
    """Può rispondere a una richiesta per quel ruolo? I palisti si riconoscono anche dai turni
    da palista dell'ultimo mese, così l'ufficio non deve impostarli tutti a mano."""
    from .models import Mansione, Postazione

    if not ruolo or ruolo in dipendente.mansioni:
        return True
    if ruolo == Mansione.PALISTA:
        da = timezone.localdate() - timedelta(days=31)
        return dipendente.turni.filter(postazione=Postazione.PALISTA, data__gte=da).exists()
    return False


def extra_per(dipendente):
    """Richieste di volontari aperte che riguardano il dipendente: quelle dei giorni in cui
    non lavora già, più quelle a cui ha già risposto."""
    from .models import TurnoExtra

    oggi = timezone.localdate()
    aperte = list(
        TurnoExtra.objects.filter(chiusa=False, data__gte=oggi).prefetch_related('disponibilita')
    )
    turni = {t.data: t for t in dipendente.turni.filter(data__in=[e.data for e in aperte])}
    risultato = []
    for e in aperte:
        mia = next((d for d in e.disponibilita.all() if d.dipendente_id == dipendente.pk), None)
        t = turni.get(e.data)
        if mia or (not (t and t.lavora) and ha_mansione(dipendente, e.ruolo)):
            e.mia = mia
            risultato.append(e)
    return risultato


def offri(extra, dipendente):
    from .models import Disponibilita

    if extra.chiusa or extra.data < timezone.localdate():
        raise RichiestaNonValida('Questa richiesta è già chiusa.')
    if not ha_mansione(dipendente, extra.ruolo):
        raise RichiestaNonValida(f'Questa richiesta è per un {extra.get_ruolo_display().lower()}.')
    Disponibilita.objects.get_or_create(extra=extra, dipendente=dipendente)


def ritira(extra, dipendente):
    disp = extra.disponibilita.filter(dipendente=dipendente).first()
    if disp and disp.confermata:
        raise RichiestaNonValida("L'ufficio ti ha già confermato: per ritirarti avvisa l'ufficio.")
    if disp:
        disp.delete()


def conferma_volontario(disponibilita):
    """Il volontario scelto lavora quel giorno: il turno compare nel suo calendario."""
    from .models import Settimana

    extra = disponibilita.extra
    if disponibilita.confermata:
        return
    if extra.mancano == 0:
        raise RichiestaNonValida('I posti sono già tutti coperti.')
    lunedi = extra.data - timedelta(days=extra.data.weekday())
    settimana = Settimana.objects.filter(lunedi=lunedi).first()
    if settimana is None:
        raise RichiestaNonValida(f'Carica prima i turni della settimana del {lunedi:%d/%m}.')
    with transaction.atomic():
        turno, _ = Turno.objects.get_or_create(
            dipendente=disponibilita.dipendente, data=extra.data, defaults={'settimana': settimana, 'fascia': extra.fascia}
        )
        turno.fascia = extra.fascia
        turno.postazione = extra.postazione or ('PALISTA' if extra.ruolo == 'PALISTA' else '')
        turno.capoturno = False
        turno.codice = 'EXTRA'
        turno.nota_modifica = 'Turno extra (volontario)'
        turno.save()
        disponibilita.confermata = True
        disponibilita.save()
        if extra.mancano == 0:
            extra.chiusa = True
            extra.save(update_fields=['chiusa'])
