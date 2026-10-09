# Sarco 4.0 — Contabilità analitica

Software di contabilità analitica (CoAn) per Sarco srl.

- **Fonte dati:** contabilità generale (CoGe) da WinWaste (Zucchetti), importata da export Excel/CSV.
- **Funzioni:** imputazione di costi e ricavi su centri di costo, regole di ripartizione, riconciliazione CoAn ↔ CoGe.
- **Hosting:** Railway (servizio web + PostgreSQL).
- **Evoluzione:** integrazione AI con ricerca vettoriale tramite l'estensione `pgvector` di PostgreSQL, senza un database separato.

## Stack previsto

- Python 3.12, Django
- PostgreSQL (con `pgvector` per la fase AI)
- Deploy automatico su Railway a ogni push sul branch `main`
