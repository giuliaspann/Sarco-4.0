"""Copia di sicurezza del database, ogni giorno (Giulia, 23/11/2026).

Il piano Hobby di Railway non fa copie del database. Ogni mattina lo script «Copia database.ps1» del PC dell'ufficio
chiama /turni/archivio/database/ con la chiave ARCHIVIO_TOKEN (la stessa dell'archivio pulizie) e salva lo zip nella
cartella condivisa, tenendo le ultime 30 copie.

Lo zip contiene:
- «dati.json»: tutti i dati dell'app (turni, pulizie, chat, manutenzione, produzione, dipendenti, utenti con le
  password cifrate…), nel formato di Django «dumpdata»;
- «LEGGIMI.txt»: come rimettere i dati in un database nuovo.
Foto e video non ci sono (stanno sul disco dell'app): quelli delle pulizie sono nell'archivio settimanale.
"""

import hmac
import tempfile
import zipfile

from django.conf import settings
from django.core.management import call_command
from django.http import FileResponse, HttpResponseForbidden
from django.utils import timezone

# fuori dalla copia: tabelle che Django ricrea da solo o che non servono (sessioni aperte, registro dell'admin)
ESCLUSI = ['contenttypes', 'auth.permission', 'sessions', 'admin.logentry']

LEGGIMI = """Copia di sicurezza del database dell'app Sarco WS del {quando}.

Per rimettere i dati (lo fa chi segue l'app, non va fatto a mano senza bisogno):
1. database nuovo e vuoto, app con lo stesso codice della data della copia;
2. python manage.py migrate
3. python manage.py flush --no-input        (toglie i dati d'esempio messi dalle migrazioni)
4. python manage.py loaddata dati.json
Le password restano quelle di prima (sono salvate cifrate). Foto e video non sono in questa copia.

Contiene dati personali dei dipendenti: tenerla in una cartella che vedono in pochi.
"""


def crea_copia():
    """(nome del file zip, file temporaneo riavvolto, quanti oggetti)."""
    import io
    import json

    quando = timezone.localtime()
    # in memoria e in UTF-8, qualunque sia la lingua del sistema (emoji nei nomi delle pulizie)
    buf = io.StringIO()
    call_command('dumpdata', natural_foreign=True, natural_primary=True, exclude=ESCLUSI, stdout=buf, verbosity=0)
    dati = buf.getvalue().encode('utf-8')
    n = len(json.loads(dati))
    zf = tempfile.TemporaryFile()
    with zipfile.ZipFile(zf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('dati.json', dati)
        z.writestr('LEGGIMI.txt', LEGGIMI.format(quando=quando.strftime('%d/%m/%Y alle %H:%M')))
    zf.seek(0)
    return f'Copia database {quando:%Y-%m-%d}.zip', zf, n


def copia_database(request):
    """Solo con la chiave dell'archivio (lo script del PC) o per il superuser: dentro ci sono i dati di tutti."""
    token = request.headers.get('X-Archivio-Token', '')
    con_chiave = bool(settings.ARCHIVIO_TOKEN) and hmac.compare_digest(token, settings.ARCHIVIO_TOKEN)
    if not con_chiave and not (request.user.is_authenticated and request.user.is_superuser):
        return HttpResponseForbidden('Copia del database: accesso non consentito.')
    nome, f, n = crea_copia()
    r = FileResponse(f, as_attachment=True, filename=nome, content_type='application/zip')
    r['X-Oggetti'] = str(n)
    return r
