"""Lettura dei numeri da una foto (display della pesa o scontrino dell'analisi) con Claude.

Funziona solo se su Railway c'è la variabile ANTHROPIC_API_KEY: senza, il tasto "Leggi dalla foto"
non compare e i numeri si scrivono a mano. I valori letti riempiono il modulo: chi inserisce li controlla
prima di salvare.
"""

import base64
import json
import logging
import os

from .models import INQUINANTI, AnalisiProdotto

log = logging.getLogger(__name__)

MODELLO = 'claude-opus-5-5'
NUMERO = {'anyOf': [{'type': 'number'}, {'type': 'null'}]}


class LetturaNonRiuscita(Exception):
    pass


def attiva():
    return bool(os.environ.get('ANTHROPIC_API_KEY'))


def _chiedi(jpeg, istruzioni, schema):
    import anthropic

    client = anthropic.Anthropic(timeout=75.0, max_retries=1)
    try:
        r = client.beta.messages.create(
            model=MODELLO,
            max_tokens=4000,
            betas=['server-side-fallback-2026-07-01'],
            fallbacks='default',
            output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': schema}},
            messages=[{
                'role': 'user',
                'content': [
                    {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg',
                                                 'data': base64.standard_b64encode(jpeg).decode()}},
                    {'type': 'text', 'text': istruzioni},
                ],
            }],
        )
    except anthropic.APIError as e:
        log.exception('Lettura foto non riuscita')
        raise LetturaNonRiuscita('Servizio di lettura non disponibile.') from e
    if r.stop_reason in ('refusal', 'max_tokens'):
        raise LetturaNonRiuscita('Non riesco a leggere questa foto.')
    testo = next((b.text for b in r.content if b.type == 'text'), '')
    try:
        return json.loads(testo)
    except ValueError as e:
        raise LetturaNonRiuscita('Non riesco a leggere questa foto.') from e


def leggi_produzione(jpeg, prodotti):
    """{prodotto_id: tonnellate} letti dal display della pesa."""
    elenco = '\n'.join(f'- {p.codice}: {p.nome} ({p.get_impianto_display()})' for p in prodotti)
    schema = {
        'type': 'object',
        'properties': {'righe': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {'codice': {'type': 'string'}, 'tonnellate': {'type': 'number'}},
            'required': ['codice', 'tonnellate'], 'additionalProperties': False,
        }}},
        'required': ['righe'], 'additionalProperties': False,
    }
    istruzioni = (
        "Foto del display di una pesa di un impianto di recupero del vetro, a fine turno. Ogni riga ha un codice "
        "(lettera, a volte con + o -), il nome del prodotto e un peso. Leggi le righe e restituisci codice e peso "
        "in tonnellate (se il display mostra kg, dividi per 1000). Usa solo questi codici:\n" + elenco +
        "\nSalta le righe che non leggi con sicurezza: è meglio un valore mancante che uno sbagliato."
    )
    per_codice = {p.codice.upper(): p for p in prodotti}
    valori = {}
    for riga in _chiedi(jpeg, istruzioni, schema).get('righe', []):
        p = per_codice.get(str(riga.get('codice', '')).strip().upper())
        t = riga.get('tonnellate')
        if p and isinstance(t, (int, float)) and 0 <= t <= 100000:
            valori[p.pk] = round(t, 2)
    return valori


def leggi_analisi(jpeg):
    """Campi del modulo dell'analisi (peso, numero e grammi per inquinante) letti dalla foto."""
    campi = {'peso_kg': NUMERO, 'numero': {'anyOf': [{'type': 'integer'}, {'type': 'null'}]},
             'campione': {'anyOf': [{'type': 'string', 'enum': list(AnalisiProdotto.Campione.values)}, {'type': 'null'}]}}
    campi.update({c: NUMERO for c, _, _ in INQUINANTI})
    schema = {'type': 'object', 'properties': campi, 'required': list(campi), 'additionalProperties': False}
    tipi = ', '.join(f'{v} = {n}' for v, n in AnalisiProdotto.Campione.choices)
    istruzioni = (
        "Foto del risultato di un'analisi di laboratorio sul vetro (macchina \"Analisi peso inquinanti\" o "
        "bilancia). Leggi: peso del campione in kg (peso_kg), numero del campione (numero, il valore dopo #), "
        "e per ogni inquinante i GRAMMI trovati (non i g/t): csp (ceramica, pietre, porcellana), vetro_ceramico, "
        "metallo, organico, plastica, cristallo. Se è scritto il tipo di campione, scegli tra: " + tipi + ". "
        "Metti null per ciò che non c'è o non leggi con sicurezza."
    )
    dati = _chiedi(jpeg, istruzioni, schema)
    return {k: v for k, v in dati.items() if v is not None and k in campi}
