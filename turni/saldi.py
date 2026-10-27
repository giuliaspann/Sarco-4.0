"""Ferie e ROL residui: l'ultimo saldo caricato dall'ufficio meno le richieste approvate dopo quella data.

Ipotesi da confermare con il consulente del lavoro: una giornata vale 8 ore; si contano i giorni in cui la
persona avrebbe lavorato (dal file turni; se la settimana non è caricata, da lunedì a venerdì).
"""

from datetime import datetime, timedelta
from decimal import Decimal

from .models import FASCE_LAVORATIVE, Fascia, RichiestaFerie, SaldoFerie

ORE_GIORNO = Decimal('8')
# chi ne ha più di così ha ferie accumulate da smaltire (20 giorni)
SOGLIA_FERIE = ORE_GIORNO * 20


def giorni_lavorativi(dip, dal, al):
    turni = {t.data: t.fascia for t in dip.turni.filter(data__range=(dal, al))}
    n, g = 0, dal
    while g <= al:
        fascia = turni.get(g)
        if fascia is None:
            n += g.weekday() < 5
        else:
            n += fascia in FASCE_LAVORATIVE or fascia in (Fascia.FERIE, Fascia.PERMESSO)
        g += timedelta(days=1)
    return n


def ore_richiesta(r):
    if r.a_ore:
        durata = datetime.combine(r.dal, r.alle) - datetime.combine(r.dal, r.dalle)
        return Decimal(durata.seconds) / 3600
    return giorni_lavorativi(r.dipendente, r.dal, r.al) * ORE_GIORNO


def residuo(dip):
    """{'al', 'ferie', 'rol', 'ferie_giorni', 'attesa_ferie', 'attesa_rol'} oppure None se non c'è un saldo."""
    saldo = dip.saldi.first()
    if saldo is None:
        return None
    usate = {RichiestaFerie.Tipo.FERIE: Decimal('0'), RichiestaFerie.Tipo.PERMESSO: Decimal('0')}
    attesa = dict(usate)
    for r in dip.richieste_ferie.filter(al__gt=saldo.al, stato__in=[RichiestaFerie.Stato.APPROVATA, RichiestaFerie.Stato.ATTESA]):
        if r.dal <= saldo.al:  # a cavallo del saldo: conta solo la parte dopo
            r.dal = saldo.al + timedelta(days=1)
        (usate if r.stato == RichiestaFerie.Stato.APPROVATA else attesa)[r.tipo] += ore_richiesta(r)
    ferie = saldo.ferie_ore - usate[RichiestaFerie.Tipo.FERIE]
    rol = saldo.rol_ore - usate[RichiestaFerie.Tipo.PERMESSO]
    return {
        'al': saldo.al,
        'ferie': ferie,
        'rol': rol,
        'ferie_giorni': ferie / ORE_GIORNO,
        'rol_giorni': rol / ORE_GIORNO,
        'attesa_ferie': attesa[RichiestaFerie.Tipo.FERIE],
        'attesa_rol': attesa[RichiestaFerie.Tipo.PERMESSO],
    }


def tutti():
    """Residuo di ogni persona attiva che ha un saldo, dalla più carica di ferie."""
    from .models import Dipendente

    righe = []
    for dip in Dipendente.objects.filter(attivo=True, saldi__isnull=False).distinct().prefetch_related('saldi'):
        r = residuo(dip)
        r['dip'] = dip
        righe.append(r)
    return sorted(righe, key=lambda r: -r['ferie'])
