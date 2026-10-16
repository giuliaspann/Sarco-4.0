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

## Modulo Turni e pulizie (`/turni/`)

Web app per telefono (installabile sulla schermata Home) che sostituisce il file turni mandato su WhatsApp.

- **Ufficio** (utenti staff): carica ogni settimana lo stesso Excel di oggi (`TURNI 2026\...\DAL gg-mm-aaaa AL ....xlsx`), vede l'anteprima e pubblica. Il foglio si sceglie da solo: `Sett.N` = settimana ISO del lunedì. Ricaricare un file corretto aggiorna i turni senza perdere le pulizie registrate. Da «Dipendenti e PIN» crea l'accesso (nome utente + PIN di 6 cifre) per ogni operaio.
- **Operai**: «I miei turni» (settimana, con chi lavorano), «Squadra» (chi c'è oggi per turno e postazione), «Pulizie» (checklist di fine turno con foto facoltativa; possono aggiungere il mezzo usato).
- **Capi turno**: «Verifica» mostra le pulizie del giorno per persona: Ok oppure Da rifare con nota.
- **Cambi turno**: dalla settimana («Cambia» su un giorno) o da «Richieste» l'operaio sceglie giorno e collega, più un eventuale giorno di recupero (scambio lavoro ↔ riposo). Il collega accetta o rifiuta, poi il responsabile turni approva: solo allora i turni dei due si scambiano.
- **Ferie e permessi**: l'operaio indica dal/al; il responsabile turni approva o rifiuta, vedendo i turni coinvolti e chi è già in ferie negli stessi giorni.
- **Responsabile turni**: chi ha il permesso «Può approvare cambi turno e ferie» (si assegna in `/admin/` all'utente o a un gruppo; i superuser ce l'hanno già). Trova le richieste in Ufficio → Richieste.
- **Excel e modifiche dell'app**: ricaricando il file, i turni cambiati da cambi o ferie approvati restano come nell'app e l'ufficio vede l'elenco delle differenze; le ferie approvate per settimane non ancora caricate vengono applicate all'import.
- **Regole pulizie**: in `/admin/` → *Mezzi e zone da pulire*. Per ogni mezzo/zona si indica chi lo pulisce (postazione, fascia, solo capo turno). I mezzi senza regola restano sceglibili dall'operaio come «mezzo usato».

Lettura dei codici del file: `1T`/`2T`/`N`/`G` = fascia; `Imp. 1`, `Imp. 2`, `Analisi`, `Superbi`, `Mulino`, `Barrotti`, `PALISTA` = postazione; `CAPO T.` = capo turno; `RIP`, `FERIE`, `FESTA`, `C.P.` = assenze. Le note a destra (ferie/richieste) le vede ciascuno per sé; il riquadro apprendisti imposta i tutor.

### Su Railway

Le foto servono su disco persistente: aggiungere un **Volume** al servizio montato su `/data` e la variabile `MEDIA_ROOT=/data/media`. Senza volume le foto si perdono a ogni deploy.
Primo utente ufficio: `python manage.py createsuperuser` dalla shell del servizio.
