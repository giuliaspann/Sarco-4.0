"""Assistente digitale: si scrive o si parla in italiano e lui legge i turni, prepara richieste e approvazioni.

Le azioni (avviso, ferie, cambio, approvazioni, modifica di un turno) non partono mai da sole: l'assistente
le propone e l'utente le conferma con un tasto. Ogni azione passa dalle stesse regole e permessi dell'app.
Funziona solo con la variabile ANTHROPIC_API_KEY su Railway (la stessa della lettura delle foto).
"""

import logging
import os
import uuid
from datetime import date, time, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import richieste as svc
from .models import (
    ORARI, AvvisoAssenza, CambioTurno, Dipendente, Fascia, ModificaTurno, Postazione, RichiestaFerie, Turno,
)

log = logging.getLogger(__name__)

MODELLO = 'claude-opus-5-5'
MAX_PASSI = 6
MAX_MESSAGGI = 80  # oltre, si riparte da una chat nuova


GIORNI = ['lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato', 'domenica']


def giorno_it(d):
    """Es. "mar 20/10": il giorno in italiano (il server non ha la lingua italiana)."""
    return f'{GIORNI[d.weekday()][:3]} {d:%d/%m}'


def attivo():
    return bool(os.environ.get('ANTHROPIC_API_KEY'))


# ---------------------------------------------------------------- chi può fare cosa


def ruoli(utente):
    dip = getattr(utente, 'dipendente', None)
    return {
        'dipendente': dip,
        'responsabile': svc.e_responsabile(utente),
        'ufficio': utente.is_staff or svc.e_responsabile(utente),
    }


def suggerimenti(utente):
    """Frasi d'esempio mostrate nella chat, diverse per ruolo."""
    r = ruoli(utente)
    frasi = []
    if r['dipendente']:
        frasi += ['Che turno faccio sabato?', 'Impianto 1 fermo dalle 20 per rottura nastro', 'Ho finito la pulizia della pala',
                  'Domani entro alle 9:30', 'Chiedo ferie dal 3 al 7 novembre', 'Vorrei cambiare il turno di giovedì con Drame']
    if r['responsabile']:
        frasi += ['Quali richieste devo approvare?', 'Approva le ferie di Rossi']
    if r['ufficio']:
        frasi += ['Chi lavora al 2° turno mercoledì?', 'Metti Crimi al 1° turno Impianto 1 venerdì']
    return frasi[:8]


# ---------------------------------------------------------------- strumenti

DATA = {'type': 'string', 'description': 'Data AAAA-MM-GG'}
ORA = {'type': 'string', 'description': 'Ora HH:MM'}


def _strumento(nome, descrizione, proprieta, richiesti):
    return {'name': nome, 'description': descrizione, 'input_schema': {
        'type': 'object', 'properties': proprieta, 'required': richiesti, 'additionalProperties': False}}


def strumenti(utente):
    r = ruoli(utente)
    t = [
        _strumento('turni_di', 'Turni pubblicati di una persona tra due date (massimo 31 giorni). '
                   'Per la persona che scrive usa nome "io".',
                   {'nome': {'type': 'string'}, 'dal': DATA, 'al': DATA}, ['nome', 'dal', 'al']),
        _strumento('chi_lavora', 'Chi lavora in un giorno, con turno e postazione. Fascia facoltativa (stringa vuota = tutte).',
                   {'giorno': DATA, 'fascia': {'type': 'string', 'enum': ['', '1T', '2T', 'N', 'G']}}, ['giorno', 'fascia']),
    ]
    if r['dipendente']:
        t += [
            _strumento('le_mie_richieste', 'Cambi, ferie, permessi e avvisi della persona che scrive, con lo stato.', {}, []),
            _strumento('proponi_avviso', 'Prepara un avviso per l\'ufficio e il capo turno: malattia, ritardo '
                       '(alle = ora in cui entra), uscita anticipata (dalle = ora in cui esce) o altro. '
                       'Ore non usate = stringa vuota. Non lo invia: l\'utente conferma con un tasto.',
                       {'tipo': {'type': 'string', 'enum': list(AvvisoAssenza.Tipo.values)}, 'giorno': DATA,
                        'dalle': ORA, 'alle': ORA, 'nota': {'type': 'string'}},
                       ['tipo', 'giorno', 'dalle', 'alle', 'nota']),
            _strumento('proponi_ferie', 'Prepara una richiesta di ferie (giorni interi) o di permesso '
                       '(un giorno, con dalle/alle se a ore; altrimenti stringhe vuote). L\'utente conferma con un tasto.',
                       {'tipo': {'type': 'string', 'enum': list(RichiestaFerie.Tipo.values)}, 'dal': DATA, 'al': DATA,
                        'dalle': ORA, 'alle': ORA, 'motivo': {'type': 'string'}},
                       ['tipo', 'dal', 'al', 'dalle', 'alle', 'motivo']),
            _strumento('proponi_cambio', 'Prepara una richiesta di cambio turno con un collega per un giorno da domani in poi: '
                       'prima risponde il collega, poi l\'ufficio. L\'utente conferma con un tasto.',
                       {'collega': {'type': 'string'}, 'giorno': DATA, 'motivo': {'type': 'string'}},
                       ['collega', 'giorno', 'motivo']),
        ]
    if r['responsabile']:
        t += [
            _strumento('richieste_da_approvare', 'Cambi turno (già accettati dal collega) e ferie/permessi in attesa dell\'ufficio.', {}, []),
            _strumento('proponi_decisione', 'Prepara l\'approvazione o il rifiuto di una richiesta (id da richieste_da_approvare). '
                       'L\'utente conferma con un tasto.',
                       {'tipo': {'type': 'string', 'enum': ['cambio', 'ferie']}, 'id': {'type': 'integer'},
                        'approva': {'type': 'boolean'}, 'nota': {'type': 'string'}},
                       ['tipo', 'id', 'approva', 'nota']),
        ]
    if r['ufficio']:
        t.append(_strumento(
            'proponi_modifica_turno', 'Prepara la modifica del turno di una persona in una settimana già caricata. '
            'La persona riceverà la notifica e dovrà dare la presa visione. Postazione vuota = nessuna. '
            'L\'utente conferma con un tasto.',
            {'nome': {'type': 'string'}, 'giorno': DATA, 'fascia': {'type': 'string', 'enum': list(Fascia.values)},
             'postazione': {'type': 'string', 'enum': [''] + list(Postazione.values)}, 'capoturno': {'type': 'boolean'}},
            ['nome', 'giorno', 'fascia', 'postazione', 'capoturno']))
    from . import assistente_app

    t += assistente_app.strumenti(utente)
    return t


def istruzioni(utente):
    r = ruoli(utente)
    oggi = timezone.localdate()
    chi = r['dipendente'].nome_breve if r['dipendente'] else utente.get_username()
    ruolo = ', '.join(n for n, si in (('dipendente', r['dipendente']), ('responsabile turni', r['responsabile']),
                                      ('ufficio', r['ufficio'])) if si) or 'utente'
    return (
        f"Sei l'assistente dell'app Sarco 4.0 di Sarco srl (impianto di recupero del vetro). Parli con {chi} ({ruolo}). "
        f"Oggi è {GIORNI[oggi.weekday()]} {oggi:%d/%m/%Y} ({oggi.isoformat()}). Orari: 1T 06-14, 2T 14-22, N 22-06, G giornaliero 8-13 e 14:30-17:30.\n"
        "Chi scrive spesso è un operaio con poco tempo, a volte detta a voce: rispondi in italiano semplice, "
        "frasi brevi, niente elenchi lunghi, niente markdown, non spiegare come funziona l'app. Trasforma \"domani\", \"sabato\", \"la settimana prossima\" "
        "in date precise e ripetile nella risposta. Il turno di notte appartiene al giorno in cui inizia (alle 22).\n"
        "Usa gli strumenti per leggere i dati: non inventare turni né nomi. Se un nome corrisponde a più persone, chiedi quale.\n"
        "Per fare qualcosa usa gli strumenti che iniziano con proponi_: preparano l'azione e l'utente la conferma con un tasto "
        "sotto il tuo messaggio. Non dire mai che è fatto: di' che basta premere Conferma. Se manca un dato importante "
        "(il giorno, l'ora), chiedilo in una frase.\n"
        "Puoi fare quasi tutto quello che si fa nell'app: turni e richieste, fermi e ripartenze degli impianti, guasti, "
        "manutenzioni fatte o programmate, pulizie (fatte, aggiuntive, richieste a un collega, non eseguibili), produzione "
        "e analisi, report, messaggi nelle chat, bacheca, turni extra, presa visione. Per una macchina cerca prima l'id "
        "con elenco_macchine; per le pulizie usa elenco_pulizie. Guasti, manutenzioni fatte e pulizie non eseguibili "
        "vogliono una foto: se manca chiedi di premere 📷 e di allegarla. Se l'utente allega la foto di un display o di "
        "un'analisi, leggi tu i numeri e proponi l'inserimento.\n"
        "Se una cosa davvero non si può fare da qui, di' dove trovarla: Area personale, Pulizie, Manutenzione, "
        "Statistiche, Messaggi."
    )


# ---------------------------------------------------------------- esecuzione


class Errore(Exception):
    pass


def _data(testo):
    try:
        return date.fromisoformat(testo)
    except (TypeError, ValueError):
        raise Errore(f'Data non valida: {testo}')


def _ora(testo):
    if not testo:
        return None
    try:
        return time.fromisoformat(testo)
    except ValueError:
        raise Errore(f'Ora non valida: {testo}')


def trova_persona(nome, utente):
    nome = (nome or '').strip()
    if nome.lower() in ('io', 'me', ''):
        dip = getattr(utente, 'dipendente', None)
        if not dip:
            raise Errore('Non sei collegato a un dipendente: indica il nome.')
        return dip
    parole = [p for p in nome.upper().replace("'", ' ').split() if len(p) > 1]
    qs = Dipendente.objects.filter(attivo=True)
    for p in parole:
        qs = qs.filter(nome__icontains=p)
    trovati = list(qs[:6])
    if not trovati:
        raise Errore(f'Nessun dipendente si chiama "{nome}".')
    if len(trovati) > 1:
        raise Errore('Più persone corrispondono: ' + ', '.join(d.nome for d in trovati) + '. Chiedi quale.')
    return trovati[0]


def _descrivi(t):
    testo = f'{giorno_it(t.data)}: {t.descrizione}'
    if t.lavora and ORARI.get(t.fascia):
        testo += f' ({ORARI[t.fascia]})'
    if t.nota_modifica:
        testo += f' [{t.nota_modifica}]'
    return testo


def leggi(nome, dati, utente):
    """Strumenti che leggono e basta: tornano subito un testo per il modello."""
    r = ruoli(utente)
    if nome == 'turni_di':
        dip = trova_persona(dati['nome'], utente)
        dal, al = _data(dati['dal']), _data(dati['al'])
        if al < dal or (al - dal).days > 31:
            raise Errore('Intervallo non valido (massimo 31 giorni).')
        turni = Turno.objects.filter(dipendente=dip, data__range=(dal, al), settimana__pubblicata=True).order_by('data')
        return f'{dip.nome}:\n' + ('\n'.join(_descrivi(t) for t in turni) or 'nessun turno pubblicato in queste date')
    if nome == 'chi_lavora':
        g = _data(dati['giorno'])
        qs = Turno.objects.filter(data=g, settimana__pubblicata=True, dipendente__attivo=True).select_related('dipendente')
        qs = [t for t in qs if t.lavora and (not dati.get('fascia') or t.fascia == dati['fascia'])]
        return '\n'.join(f'{t.dipendente.nome_breve}: {t.descrizione}' for t in sorted(qs, key=lambda t: (t.fascia, t.postazione))) or 'nessuno'
    if nome == 'le_mie_richieste':
        dip = r['dipendente']
        righe = [f'Cambio con {(c.collega if c.richiedente_id == dip.pk else c.richiedente).nome_breve} '
                 f'{c.giorno1:%d/%m}: {c.get_stato_display()}'
                 for c in CambioTurno.objects.filter(Q(richiedente=dip) | Q(collega=dip))[:8]]
        righe += [f'{f.get_tipo_display()} {f.dal:%d/%m}-{f.al:%d/%m} {f.orario}: {f.get_stato_display()}' for f in dip.richieste_ferie.all()[:8]]
        righe += [f'Avviso {a.get_tipo_display()} {a.data:%d/%m} {a.orario}' for a in dip.avvisi.all()[:5]]
        return '\n'.join(righe) or 'nessuna richiesta'
    if nome == 'richieste_da_approvare':
        righe = [f'cambio id={c.pk}: {c.richiedente.nome_breve} ↔ {c.collega.nome_breve} il {c.giorno1:%d/%m}'
                 for c in CambioTurno.objects.filter(stato=CambioTurno.Stato.ATTESA_UFFICIO).select_related('richiedente', 'collega')]
        righe += [f'ferie id={f.pk}: {f.dipendente.nome_breve} {f.get_tipo_display()} {f.dal:%d/%m}-{f.al:%d/%m} {f.orario}'
                  for f in RichiestaFerie.objects.filter(stato=RichiestaFerie.Stato.ATTESA).select_related('dipendente')]
        return '\n'.join(righe) or 'niente da approvare'
    raise Errore('Strumento sconosciuto.')


def prepara(nome, dati, utente):
    """Controlla una proposta e restituisce il riassunto da far confermare (senza eseguirla)."""
    r = ruoli(utente)
    if nome == 'proponi_avviso':
        g, dalle, alle = _data(dati['giorno']), _ora(dati['dalle']), _ora(dati['alle'])
        if abs((g - timezone.localdate()).days) > 30:
            raise Errore('La data è troppo lontana.')
        tipo = AvvisoAssenza.Tipo(dati['tipo'])
        if tipo == AvvisoAssenza.Tipo.USCITA and not dalle:
            raise Errore('Serve l\'ora in cui esce.')
        if tipo == AvvisoAssenza.Tipo.RITARDO and not alle:
            raise Errore('Serve l\'ora in cui entra.')
        a = AvvisoAssenza(tipo=tipo, data=g, dalle=dalle if tipo != 'RITARDO' else None, alle=alle if tipo != 'USCITA' else None)
        return f'Avviso {tipo.label.lower()} · {giorno_it(g)}' + (f' · {a.orario}' if a.orario else '')
    if nome == 'proponi_ferie':
        tipo = RichiestaFerie.Tipo(dati['tipo'])
        dal, al = _data(dati['dal']), _data(dati['al'])
        dalle, alle = _ora(dati['dalle']), _ora(dati['alle'])
        if dal <= timezone.localdate():
            raise Errore('Si chiede da domani in poi.')
        if tipo == RichiestaFerie.Tipo.PERMESSO and dalle and alle:
            if alle <= dalle:
                raise Errore('L\'ora di fine deve essere dopo quella di inizio.')
            return f'Permesso {giorno_it(dal)} dalle {dalle:%H:%M} alle {alle:%H:%M}'
        if al < dal:
            raise Errore('La data di fine è prima di quella di inizio.')
        return f'{tipo.label} dal {giorno_it(dal)} al {giorno_it(al)} ({(al - dal).days + 1} giorni)'
    if nome == 'proponi_cambio':
        collega = trova_persona(dati['collega'], utente)
        g = _data(dati['giorno'])
        righe, _ = svc.anteprima(r['dipendente'], collega, [g])
        x = righe[0]
        return (f'Cambio turno con {collega.nome_breve} · {giorno_it(g)}: tu passi da {x["io_prima"].descrizione} '
                f'a {x["collega_prima"].descrizione}')
    if nome == 'proponi_decisione':
        verbo = 'Approva' if dati['approva'] else 'Rifiuta'
        if dati['tipo'] == 'cambio':
            c = CambioTurno.objects.filter(pk=dati['id'], stato=CambioTurno.Stato.ATTESA_UFFICIO).first()
            if not c:
                raise Errore('Richiesta di cambio non trovata o non in attesa.')
            return f'{verbo} il cambio {c.richiedente.nome_breve} ↔ {c.collega.nome_breve} del {c.giorno1:%d/%m}'
        f = RichiestaFerie.objects.filter(pk=dati['id'], stato=RichiestaFerie.Stato.ATTESA).first()
        if not f:
            raise Errore('Richiesta di ferie non trovata o non in attesa.')
        return f'{verbo} {f.get_tipo_display().lower()} di {f.dipendente.nome_breve} {f.dal:%d/%m}-{f.al:%d/%m} {f.orario}'.strip()
    if nome == 'proponi_modifica_turno':
        dip = trova_persona(dati['nome'], utente)
        g = _data(dati['giorno'])
        t = Turno.objects.filter(dipendente=dip, data=g).first()
        if not t:
            raise Errore(f'Il turno di {dip.nome_breve} del {g:%d/%m} non è caricato.')
        nuovo = Turno(fascia=dati['fascia'], postazione=dati['postazione'], capoturno=dati['capoturno'], codice=t.codice)
        return f'Turno di {dip.nome_breve} {giorno_it(g)}: da {t.descrizione} a {nuovo.descrizione}'
    raise Errore('Strumento sconosciuto.')


def esegui(nome, dati, utente):
    """Esegue una proposta confermata dall'utente. Ricontrolla tutto: i dati possono essere cambiati."""
    r = ruoli(utente)
    prepara(nome, dati, utente)
    if nome == 'proponi_avviso':
        dalle, alle = _ora(dati['dalle']), _ora(dati['alle'])
        tipo = dati['tipo']
        AvvisoAssenza.objects.create(
            dipendente=r['dipendente'], data=_data(dati['giorno']), tipo=tipo, nota=dati['nota'][:300],
            dalle=None if tipo in ('RITARDO', 'MALATTIA') else dalle, alle=None if tipo in ('USCITA', 'MALATTIA') else alle)
        return "Avviso inviato all'ufficio e al capo turno."
    if nome == 'proponi_ferie':
        svc.crea_ferie(r['dipendente'], dati['tipo'], _data(dati['dal']), _data(dati['al']), dati['motivo'],
                       _ora(dati['dalle']), _ora(dati['alle']))
        return "Richiesta inviata all'ufficio."
    if nome == 'proponi_cambio':
        c = svc.crea_cambio(r['dipendente'], trova_persona(dati['collega'], utente), _data(dati['giorno']), None, dati['motivo'])
        return f'Richiesta inviata a {c.collega.nome_breve}: prima risponde lui, poi l\'ufficio.'
    if nome == 'proponi_decisione':
        if not r['responsabile']:
            raise Errore('Non hai il permesso.')
        if dati['tipo'] == 'cambio':
            svc.decisione_ufficio_cambio(CambioTurno.objects.get(pk=dati['id']), utente, dati['approva'], dati['nota'])
        else:
            svc.decisione_ufficio_ferie(RichiestaFerie.objects.get(pk=dati['id']), utente, dati['approva'], dati['nota'])
        return 'Fatto: approvata.' if dati['approva'] else 'Fatto: rifiutata.'
    if nome == 'proponi_modifica_turno':
        if not r['ufficio']:
            raise Errore('Non hai il permesso.')
        from .views import avvisa_modifiche

        dip = trova_persona(dati['nome'], utente)
        g = _data(dati['giorno'])
        with transaction.atomic():
            t = Turno.objects.select_for_update().get(dipendente=dip, data=g)
            prima = t.descrizione
            t.fascia, t.postazione, t.capoturno = dati['fascia'], dati['postazione'], dati['capoturno']
            t.nota_modifica = 'Modificato dall\'ufficio'
            t.save()
            m = None
            if g >= timezone.localdate() and prima != t.descrizione:
                m = ModificaTurno.objects.create(dipendente=dip, data=g, prima=prima[:80], dopo=t.descrizione[:80])
        if m:
            avvisa_modifiche(t.settimana, [m])
        return f'Turno modificato: {dip.nome_breve} riceve la notifica e deve dare la presa visione.'
    raise Errore('Azione sconosciuta.')


# ---------------------------------------------------------------- conversazione


def rispondi(conversazione, testo, utente, foto=None):
    """Aggiunge il messaggio dell'utente, fa girare Claude con gli strumenti e restituisce
    (testo della risposta, proposte da confermare). La storia si allunga e basta: niente si riscrive."""
    import anthropic

    from .lettura import CHIAVE_SBAGLIATA, chiave_valida

    if not chiave_valida():
        log.error('ANTHROPIC_API_KEY non valida (non la si usa)')
        raise Errore(CHIAVE_SBAGLIATA)
    client = anthropic.Anthropic(timeout=75.0, max_retries=1)
    messaggi = conversazione.messaggi
    if foto:
        import base64

        from .manutenzione import comprimi_foto

        jpeg = comprimi_foto(foto).read()
        conversazione.foto.save('chat.jpg', __import__('django.core.files.base', fromlist=['ContentFile']).ContentFile(jpeg), save=False)
        piccola = _rimpicciolisci(jpeg)
        messaggi.append({'role': 'user', 'content': [
            {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': base64.standard_b64encode(piccola).decode()}},
            {'type': 'text', 'text': (testo or 'Ecco la foto.')[:2000] + ' [foto allegata]'},
        ]})
    else:
        messaggi.append({'role': 'user', 'content': testo[:2000]})
    proposte = []
    risposta = ''
    for _ in range(MAX_PASSI):
        try:
            r = client.beta.messages.create(
                model=MODELLO, max_tokens=4000, system=istruzioni(utente), tools=strumenti(utente),
                messages=messaggi, output_config={'effort': 'low'},
                betas=['server-side-fallback-2026-07-01'], fallbacks='default',
            )
        except anthropic.APIError:
            log.exception('Assistente non disponibile')
            messaggi.pop()
            raise Errore('In questo momento non riesco a rispondere: riprova tra poco.')
        messaggi.append({'role': 'assistant', 'content': [b.to_dict() for b in r.content]})
        risposta = '\n'.join(b.text for b in r.content if b.type == 'text').strip()
        if r.stop_reason == 'refusal':
            risposta = risposta or 'Su questo non posso aiutarti.'
            break
        chiamate = [b for b in r.content if b.type == 'tool_use']
        if r.stop_reason != 'tool_use' or not chiamate:
            break
        risultati = []
        from . import assistente_app

        for c in chiamate:
            try:
                if assistente_app.gestisce(c.name) and c.name.startswith('proponi_'):
                    riassunto = assistente_app.prepara(c.name, c.input, utente, ha_foto=bool(conversazione.foto))
                    p = {'id': uuid.uuid4().hex[:12], 'nome': c.name, 'dati': c.input, 'riassunto': riassunto,
                         'foto': conversazione.foto.name if conversazione.foto else ''}
                    if p['foto']:
                        p['riassunto'] += ' · con foto'
                    conversazione.proposte = [*conversazione.proposte, p]
                    proposte.append(p)
                    esito = f'Proposta mostrata all\'utente: "{p["riassunto"]}". Non è ancora fatta: aspetta che prema Conferma.'
                elif assistente_app.gestisce(c.name):
                    esito = assistente_app.leggi(c.name, c.input, utente)
                elif c.name.startswith('proponi_'):
                    riassunto = prepara(c.name, c.input, utente)
                    p = {'id': uuid.uuid4().hex[:12], 'nome': c.name, 'dati': c.input, 'riassunto': riassunto}
                    conversazione.proposte = [*conversazione.proposte, p]
                    proposte.append(p)
                    esito = f'Proposta mostrata all\'utente: "{riassunto}". Non è ancora fatta: aspetta che prema Conferma.'
                else:
                    esito = leggi(c.name, c.input, utente)
                risultati.append({'type': 'tool_result', 'tool_use_id': c.id, 'content': esito})
            except (Errore, assistente_app.Errore, svc.RichiestaNonValida, ValueError, KeyError, TypeError) as e:
                risultati.append({'type': 'tool_result', 'tool_use_id': c.id, 'content': str(e), 'is_error': True})
        messaggi.append({'role': 'user', 'content': risultati})
    conversazione.messaggi = messaggi
    conversazione.save()
    return risposta or 'Ecco qui.', proposte


def conferma(conversazione, id_proposta, accetta, utente):
    p = next((p for p in conversazione.proposte if p['id'] == id_proposta), None)
    if not p:
        raise Errore('Questa proposta non è più valida.')
    conversazione.proposte = [x for x in conversazione.proposte if x['id'] != id_proposta]
    if accetta:
        from . import assistente_app

        try:
            if assistente_app.gestisce(p['nome']):
                foto = None
                if p.get('foto'):
                    from django.core.files.base import ContentFile
                    from django.core.files.storage import default_storage

                    with default_storage.open(p['foto'], 'rb') as f:
                        foto = ContentFile(f.read(), name='foto.jpg')
                esito = assistente_app.esegui(p['nome'], p['dati'], utente, foto)
            else:
                esito = esegui(p['nome'], p['dati'], utente)
        except (Errore, assistente_app.Errore, svc.RichiestaNonValida, ValueError, KeyError, TypeError, OSError) as e:
            esito = f'Non è stato possibile: {e}'
    else:
        esito = 'Annullato.'
    # l'assistente lo saprà al prossimo messaggio (la storia si allunga, non si riscrive)
    conversazione.messaggi = [*conversazione.messaggi, {'role': 'user', 'content': f'[{p["riassunto"]}: {esito}]'},
                              {'role': 'assistant', 'content': 'Ok.'}]
    conversazione.save()
    return esito


def _rimpicciolisci(jpeg):
    """Per Claude basta una foto da 1000 px: costa meno e la storia della chat resta leggera."""
    from io import BytesIO

    from PIL import Image

    img = Image.open(BytesIO(jpeg))
    img.thumbnail((1000, 1000))
    buf = BytesIO()
    img.convert('RGB').save(buf, 'JPEG', quality=70)
    return buf.getvalue()
