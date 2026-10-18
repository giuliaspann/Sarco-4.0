"""Mansioni dei dipendenti, dal foglio dell'ufficio.

Usata una volta per chi è già nell'app (migrazione 0009) e poi per ogni dipendente
nuovo creato dal caricamento dell'Excel. Dopo si correggono da Ufficio > Dipendenti.
"""

LISTA = {
    'CRIMI BENITO': 'OPERAIO',
    'VALENTI MASSIMO': 'OPERAIO',
    'PUGLIESE GIUSEPPE': 'OPERAIO',
    'GIGANTE DIEGO': 'OPERAIO',
    'JARJU NABIE': 'OPERAIO',
    'SONKO ABDOU': 'OPERAIO',
    'ALAGNA PIETRO': 'OPERAIO',
    'GENESIO VALERIO': 'OPERAIO',
    "SPANO' A. MAURO": 'OPERAIO',
    'PLAIA ANTONINO': 'OPERAIO',
    'DI GIROLAMO GIANVITO': 'OPERAIO',
    'ODDO FEDERICO': 'OPERAIO',
    'RIPOSO GIUSEPPE': 'OPERAIO',
    'GENNA FRANCESCO': 'OPERAIO',
    'LAUDICINA GIUSEPPE': 'OPERAIO',
    'LAUDICINA DAVIDE': 'OPERAIO',
    'FERRO GIACOMO': 'OPERAIO',
    'DIANE GUEDALY': 'OPERAIO',
    'DRAME BOUBA': 'OPERAIO',
    'SAMMARTANO CARLO': 'OPERAIO',
    'DI GIROLAMO FRANCESCO': 'OPERAIO',
    'SANTO BALDASSARE': 'OPERAIO',
    'GENTILE FABRIZIO': 'MANUTENTORE',
    'GALASSI MARIO': 'OPERAIO',
    'LI VIGNI LUIGI': 'PALISTA',
    'LOMBARDO GABRIELE': 'PIAZZALE',
    'NIZZA MIRCO': 'MANUTENTORE',
    'TORRE VITO': 'MANUTENTORE',
    'COTTONE ANTONINO': 'MANUTENTORE',
    'PANTALEO LEONARDO': 'MANUTENTORE',
    'TITONE GIUSEPPE': 'PALISTA',
    'MODELLO FRANCESCO': 'PALISTA',
    'GIACALONE VINCENZO': 'OPERAIO,PALISTA',
    'INGRASSIA PAOLO': 'AUTISTA',
    'RALLO GASPARE': 'AUTISTA',
    'ALAGNA GIUSEPPE': 'AUTISTA',
    'VELIERO GIUSEPPE': 'UFFICIO',
    'PICCIOTTO MARIO': 'UFFICIO',
}


def mansione_per(nome):
    """Mansione dalla lista: prima il nome identico, poi uno scritto in modo simile."""
    from .importa import stesso_nome

    nome = nome.upper()
    if nome in LISTA:
        return LISTA[nome]
    for chiave, valore in LISTA.items():
        if stesso_nome(chiave, nome):
            return valore
    return None
