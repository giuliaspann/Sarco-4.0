"""Archivio settimanale delle pulizie (Giulia, 22/11/2026).

Ogni settimana un file zip con:
- «Pulizie AAAA-MM-GG.xlsx»: una riga per pulizia (giorno, turno, area, chi, stato, orari, conferme, note, nomi dei file);
- la cartella «Foto e video» con tutte le foto e i video della settimana, con nomi che si capiscono.

Lo scarica il PC dell'ufficio (Railway non vede la cartella condivisa): lo script «Scarica archivio pulizie.ps1»
lo salva in «Funzioni/1. Pulizie/0. Archivio/<anno>/». Ogni scaricamento resta segnato (ArchivioPulizie),
così in seguito si potranno togliere dall'app i file vecchi già al sicuro sulla condivisa.
"""

import io
import os
import re
import zipfile
from datetime import timedelta

from django.utils import timezone


def _pulito(testo, massimo=60):
    testo = re.sub(r'[\\/:*?"<>|\r\n\t]+', ' ', str(testo or '')).strip()
    return ' '.join(testo.split())[:massimo].strip() or 'senza nome'


def _ora(d):
    return timezone.localtime(d).strftime('%d/%m/%Y %H:%M') if d else ''


def _chi(u):
    if u is None:
        return ''
    return getattr(getattr(u, 'dipendente', None), 'nome_breve', '') or u.get_username()


def file_della_pulizia(p):
    """[(campo o allegato, momento, FieldFile)] di una pulizia."""
    out = []
    for campo, momento in (('foto_richiesta', 'richiesta'), ('foto_prima', 'prima'), ('foto', 'dopo')):
        f = getattr(p, campo)
        if f:
            out.append((momento, f))
    for a in p.allegati.all():
        out.append((a.get_momento_display().split(' ')[0].lower() + (' video' if a.video else ''), a.file))
    return out


def crea_zip(lunedi):
    """(nome del file zip, file temporaneo già riavvolto, quante pulizie, quanti file) della settimana che inizia da `lunedi`.
    Lo zip si scrive su disco (una settimana con i video può pesare centinaia di MB): il file sparisce quando lo si chiude."""
    import tempfile

    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    from . import piano_pulizie as pp
    from .models import Pulizia

    domenica = lunedi + timedelta(days=6)
    pulizie = list(Pulizia.objects.filter(turno__data__range=(lunedi, domenica))
                   .select_related('turno__dipendente', 'elemento', 'fatta_da', 'ok_capoturno_da__dipendente',
                                   'verificata_da__dipendente', 'richiesta_da__dipendente')
                   .prefetch_related('allegati').order_by('turno__data', 'turno__fascia', 'elemento__ordine', 'pk'))
    buf = tempfile.TemporaryFile()
    usati = set()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Pulizie'
    intest = ['Giorno', 'Turno', 'Area', 'Pulizia', 'Persona', 'Fatta da', 'Stato', 'Fatta il', 'Confermata dal Capo Turno',
              'Convalidata / verificata', 'Nota', 'Nota di verifica', 'Foto e video (cartella «Foto e video»)']
    ws.append([f'Pulizie dal {lunedi:%d/%m/%Y} al {domenica:%d/%m/%Y}'])
    ws['A1'].font = Font(bold=True, size=13)
    ws.append(intest)
    for c in ws[2]:
        c.font = Font(bold=True, color='FFFFFF')
        c.fill = PatternFill('solid', fgColor='1F3864')
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    n_file = 0
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in pulizie:
            s = pp.sigla(p.turno.fascia) or p.turno.fascia
            persona = p.turno.dipendente.nome_breve
            nomi = []
            for momento, f in file_della_pulizia(p):
                est = (os.path.splitext(f.name)[1] or '.jpg').lower()
                base = f'{p.turno.data:%Y-%m-%d} {s} {_pulito(p.titolo, 40)} - {_pulito(persona, 30)} - {momento}'
                nome, k = base + est, 2
                while nome.lower() in usati:
                    nome, k = f'{base} ({k}){est}', k + 1
                try:
                    with f.open('rb') as fh:
                        z.writestr(f'Foto e video/{nome}', fh.read())
                except (FileNotFoundError, OSError):
                    nome += ' (file mancante)'
                else:
                    n_file += 1
                usati.add(nome.lower())
                nomi.append(nome)
            ok_ct = f'{_chi(p.ok_capoturno_da)} {_ora(p.ok_capoturno_il)}'.strip()
            conv = f'{_chi(p.verificata_da)} {_ora(p.verificata_il)}'.strip()
            ws.append([p.turno.data.strftime('%d/%m/%Y'), s, dict(pp.AREE).get(pp.area_di(p.turno, p.elemento), ''), p.titolo, persona,
                       p.fatta_da.nome_breve if p.fatta_da_id else '', p.get_stato_display(), _ora(p.fatta_il), ok_ct, conv,
                       p.nota, p.nota_verifica, '\n'.join(nomi)])
        for i, w in enumerate([12, 7, 20, 32, 22, 18, 16, 17, 26, 26, 40, 30, 60], start=1):
            ws.column_dimensions[get_column_letter(i)].width = w
        for riga in ws.iter_rows(min_row=3):
            for c in riga:
                c.alignment = Alignment(vertical='top', wrap_text=True)
        ws.freeze_panes = 'A3'
        ws.auto_filter.ref = f'A2:M{max(ws.max_row, 2)}'
        xls = io.BytesIO()
        wb.save(xls)
        z.writestr(f'Pulizie {lunedi:%Y-%m-%d}.xlsx', xls.getvalue())
    buf.seek(0)
    return f'Pulizie {lunedi:%Y-%m-%d}.zip', buf, len(pulizie), n_file
