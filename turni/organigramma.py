"""Profili dall'organigramma 2026 e chat aziendali.

Applicati una volta con la migrazione 0012. Gli accessi (nome utente e PIN) li crea poi
l'ufficio da Ufficio > Dipendenti: il PIN arriva all'ufficio turni.
"""

# nome (come nel file turni: COGNOME NOME), qualifica, ruolo nell'app
PROFILI = [
    ('SPANÒ ANTONIO UGO', 'Direttore Generale e Direttore Tecnico', 'DIREZIONE'),
    ('LI VIGNI LAURA', 'Assistente Direzione Generale, DPO', 'DIREZIONE'),
    ('BONOMO MICHELANGELO', 'Responsabile Commerciale e Acquisti', 'DIREZIONE'),
    ('MARCHESE LEONARDO', 'Responsabile Produzione e Manutenzione', 'DIREZIONE'),
    ('ANCONA MARIO', 'Responsabile Qualità, Ambiente e Sicurezza, Responsabile Logistica, Responsabile turni', 'RESP_TURNI'),
]

# già presenti dal file turni: si aggiunge solo la qualifica
QUALIFICHE = {
    'VELIERO GIUSEPPE': 'Apprendista operatore pesa e gestione rifiuti/MPS',
    'PICCIOTTO MARIO': 'Addetto alla pesa e gestione rifiuti/MPS, Addetto SPP',
    'LOMBARDO GABRIELE': 'Coordinatore Operativo Impianto',
    'TORRE VITO': 'Capo Manutentori, RLS',
    'GALASSI MARIO': 'Addetto Laboratorio Analisi',
}

# chat aziendali (tutte aperte a tutti; la direzione è sempre dentro)
CHAT = [
    ('Produzione e Qualità', '🏭'),
    ('Pulizia', '🧹'),
    ('Manutenzione', '🔧'),
    ('Laboratorio Analisi', '🧪'),
    ('Turni', '📅'),
]
