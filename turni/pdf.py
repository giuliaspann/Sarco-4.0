"""PDF semplice per i report dell'archivio, senza librerie esterne: testo in Helvetica e foto JPEG (ridotte con Pillow)."""

import io
import re

from PIL import Image, ImageOps

A4 = (595.28, 841.89)
MARGINE = 40
FOTO_LATO = 700  # px: basta per vederle bene stampate e tiene il file leggero

# larghezze dei caratteri di Helvetica (millesimi del corpo), da spazio a tilde
_LARGHEZZE = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556,
    556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556,
    556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]
_EMOJI = re.compile('[\U0001F000-\U0001FFFF☀-➿️‍]')


def _pulisci(testo):
    testo = _EMOJI.sub('', str(testo)).replace('\r', '').replace('\t', ' ')
    return testo.encode('cp1252', errors='replace').decode('cp1252')


def _larghezza(testo, corpo, grassetto=False):
    tot = sum(_LARGHEZZE[ord(c) - 32] if 32 <= ord(c) <= 126 else 556 for c in testo)
    return tot * corpo / 1000 * (1.07 if grassetto else 1)


def _escape(testo):
    return testo.encode('cp1252', errors='replace').replace(b'\\', b'\\\\').replace(b'(', b'\\(').replace(b')', b'\\)')


class Documento:
    def __init__(self, titolo):
        self.titolo = _pulisci(titolo)
        self.pagine = []
        self.immagini = []
        self.larghezza = A4[0] - 2 * MARGINE
        self._nuova_pagina()

    def _nuova_pagina(self):
        self.pagine.append([])
        self.y = A4[1] - MARGINE

    def _serve(self, altezza):
        if self.y - altezza < MARGINE + 18:
            self._nuova_pagina()

    def _scrivi(self, x, y, riga, corpo, grassetto, colore):
        r, g, b = colore
        self.pagine[-1].append(b'BT /F%d %.1f Tf %.3f %.3f %.3f rg %.2f %.2f Td (' % (2 if grassetto else 1, corpo, r, g, b, x, y)
                               + _escape(riga) + b') Tj ET')

    def _a_capo(self, testo, corpo, grassetto, larghezza):
        righe = []
        for paragrafo in testo.split('\n'):
            riga = ''
            for parola in paragrafo.split(' '):
                prova = f'{riga} {parola}' if riga else parola
                if _larghezza(prova, corpo, grassetto) <= larghezza or not riga:
                    riga = prova
                else:
                    righe.append(riga)
                    riga = parola
            righe.append(riga)
        return righe

    def testo(self, testo, corpo=10, grassetto=False, colore=(0.1, 0.1, 0.1), rientro=0):
        for riga in self._a_capo(_pulisci(testo), corpo, grassetto, self.larghezza - rientro):
            self._serve(corpo * 1.35)
            self.y -= corpo * 1.35
            self._scrivi(MARGINE + rientro, self.y + corpo * 0.3, riga, corpo, grassetto, colore)

    def voce(self, etichetta, valore, corpo=9.5):
        """«Etichetta: valore» con l'etichetta in grigio."""
        etichetta = _pulisci(etichetta) + ': '
        rientro = min(_larghezza(etichetta, corpo, True) + 4, 140)
        righe = self._a_capo(_pulisci(valore), corpo, False, self.larghezza - rientro)
        for i, riga in enumerate(righe):
            self._serve(corpo * 1.35)
            self.y -= corpo * 1.35
            if i == 0:
                self._scrivi(MARGINE, self.y + corpo * 0.3, etichetta, corpo, True, (0.42, 0.45, 0.5))
            self._scrivi(MARGINE + rientro, self.y + corpo * 0.3, riga, corpo, False, (0.1, 0.1, 0.1))

    def tabella(self, intestazione, righe, larghezze, corpo=9.5):
        """larghezze in frazioni della pagina utile; le celle lunghe vanno a capo."""
        colonne = [self.larghezza * f for f in larghezze]

        def fila(celle, grassetto):
            testi = [self._a_capo(_pulisci(c), corpo, grassetto, w - 6) for c, w in zip(celle, colonne)]
            alta = max(len(t) for t in testi) * corpo * 1.3 + 6
            self._serve(alta)
            if grassetto:
                self.pagine[-1].append(b'0.93 0.95 0.93 rg %.2f %.2f %.2f %.2f re f' % (MARGINE, self.y - alta, self.larghezza, alta))
            x = MARGINE
            for t, w in zip(testi, colonne):
                for n, riga in enumerate(t):
                    self._scrivi(x + 3, self.y - 3 - corpo * (n + 1) * 1.3 + corpo * 0.3, riga, corpo, grassetto, (0.1, 0.1, 0.1))
                x += w
            self.y -= alta
            self.pagine[-1].append(b'0.8 0.82 0.85 RG 0.5 w %.2f %.2f m %.2f %.2f l S' % (MARGINE, self.y, A4[0] - MARGINE, self.y))

        fila(intestazione, True)
        for r in righe:
            fila(r, False)

    def spazio(self, altezza=6):
        self.y -= altezza

    def linea(self):
        self._serve(10)
        self.y -= 6
        self.pagine[-1].append(b'0.85 0.87 0.9 RG 0.6 w %.2f %.2f m %.2f %.2f l S' % (MARGINE, self.y, A4[0] - MARGINE, self.y))
        self.y -= 6

    def foto(self, elenco, per_riga=3):
        """elenco: [(didascalia, file)] — file aperto da un ImageField. Le foto illeggibili si saltano."""
        lette = []
        for didascalia, file in elenco:
            try:
                with file.open('rb') as f:
                    img = ImageOps.exif_transpose(Image.open(f))
                    img.thumbnail((FOTO_LATO, FOTO_LATO))
                    img = img.convert('RGB')
                    dati = io.BytesIO()
                    img.save(dati, 'JPEG', quality=70)
            except Exception:
                continue
            lette.append((_pulisci(didascalia), img.size, dati.getvalue()))
        spazio = 8
        cella = (self.larghezza - spazio * (per_riga - 1)) / per_riga
        for i in range(0, len(lette), per_riga):
            fila = lette[i:i + per_riga]
            altezze = [cella * h / w if w >= h else cella for _, (w, h), _ in fila]
            alta = max(altezze) + 14
            self._serve(alta + 4)
            self.y -= 4
            for j, ((didascalia, (w, h), dati), altezza) in enumerate(zip(fila, altezze)):
                largh = altezza * w / h
                x = MARGINE + j * (cella + spazio)
                self.immagini.append((w, h, dati))
                n = len(self.immagini)
                self.pagine[-1].append(b'q %.2f 0 0 %.2f %.2f %.2f cm /Im%d Do Q' % (largh, altezza, x, self.y - altezza, n))
                self._scrivi(x, self.y - altezza - 10, didascalia, 7.5, False, (0.42, 0.45, 0.5))
            self.y -= alta

    def pdf(self):
        oggetti = [b'<< /Type /Catalog /Pages 2 0 R >>', None,
                   b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>',
                   b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>']
        primo_img = len(oggetti) + 1
        for w, h, dati in self.immagini:
            oggetti.append(b'<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8 '
                           b'/Filter /DCTDecode /Length %d >>\nstream\n' % (w, h, len(dati)) + dati + b'\nendstream')
        risorse_img = b' '.join(b'/Im%d %d 0 R' % (i + 1, primo_img + i) for i in range(len(self.immagini)))
        pagine = []
        totale = len(self.pagine)
        for n, comandi in enumerate(self.pagine, 1):
            piede = _pulisci(f'{self.titolo} · pagina {n} di {totale}')
            comandi = comandi + [b'BT /F1 8 Tf 0.5 0.5 0.5 rg %.2f %.2f Td (' % (MARGINE, MARGINE - 16) + _escape(piede) + b') Tj ET']
            flusso = b'\n'.join(comandi)
            oggetti.append(b'<< /Length %d >>\nstream\n' % len(flusso) + flusso + b'\nendstream')
            contenuto = len(oggetti)
            oggetti.append(b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R '
                           b'/Resources << /Font << /F1 3 0 R /F2 4 0 R >> /XObject << %s >> >> >>'
                           % (A4[0], A4[1], contenuto, risorse_img))
            pagine.append(len(oggetti))
        oggetti[1] = b'<< /Type /Pages /Kids [%s] /Count %d >>' % (b' '.join(b'%d 0 R' % p for p in pagine), len(pagine))
        uscita = io.BytesIO()
        uscita.write(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
        posizioni = []
        for i, corpo in enumerate(oggetti, 1):
            posizioni.append(uscita.tell())
            uscita.write(b'%d 0 obj\n' % i + corpo + b'\nendobj\n')
        xref = uscita.tell()
        uscita.write(b'xref\n0 %d\n0000000000 65535 f \n' % (len(oggetti) + 1))
        for p in posizioni:
            uscita.write(b'%010d 00000 n \n' % p)
        uscita.write(b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (len(oggetti) + 1, xref))
        return uscita.getvalue()
