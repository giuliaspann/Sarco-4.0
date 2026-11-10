"""Caricamento del file del responsabile turni: foglio "Layout Turni" + "Collegamento Nomi"."""

from datetime import date, datetime
from io import BytesIO

import openpyxl
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from . import importa
from .models import Dipendente, Fascia, Postazione, Turno

LUNEDI = date(2026, 11, 9)
GIORNI = ['Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato', 'Domenica']

# (area, turno, ruolo, sigla, lun…dom); il turno vuoto continua quello della riga sopra
RIGHE = [
    ('Impianto 1', '1T', 'Capo Turno', 'CT', 'Oddo', 'Oddo', '-', '-', '-', '-', '-'),
    ('Impianto 1', '', 'Operatore di Linea', 'OdL', 'Jarju', 'Jarju', '-', '-', '-', '-', '-'),
    ('Impianto 1', '', 'Palista', 'Pal', 'Titone', 'Titone', '-', '-', '-', '-', '-'),
    ('Impianto 1', '2T', 'Palista', 'Pal', 'Modello', '-', '-', '-', '-', '-', '-'),
    ('Piazzale - Pala', '1T', 'Palista', 'Pal', 'Titone', 'Titone', '-', '-', '-', '-', '-'),
    ('Piazzale - Pala', '2T', 'Palista', 'Pal', 'Modello', '-', '-', '-', '-', '-', '-'),
    ('Sabbia - Sarco', '2T', 'Operatore di Linea', 'OdL', 'Modello', '-', '-', '-', '-', '-', '-'),
    ('Sabbia - Superbi', '1T', 'Operatore di Linea', 'OdL', 'X', '-', '-', '-', '-', '-', '-'),
    ('Piazzale - Rotovaglio', '1T', 'Palista', 'Pal', '-', 'Ignoto', '-', '-', '-', '-', '-'),
]
NOMI = [('Oddo', 'ODDO FEDERICO'), ('Jarju', 'JARJU NABIE'), ('Titone', 'TITONE GIUSEPPE'),
        ('Modello', 'MODELLO FRANCESCO'), ('Rallo', 'RALLO GASPARE'), ('X', '(segnaposto)')]


def file_layout(righe=RIGHE, nomi=NOMI, lunedi=LUNEDI):
    wb = openpyxl.Workbook()
    vista = wb.active
    vista.title = 'Vista Dipendenti'
    vista['B1'] = 'Lunedì della settimana:'
    vista['C1'] = datetime.combine(lunedi, datetime.min.time())
    ws = wb.create_sheet('Layout Turni')
    for i, g in enumerate(GIORNI):
        ws.cell(2, 7 + i, g)
    for c, t in enumerate(['Area', 'Area (Abbr.)', 'Turno', 'Ruolo', 'Ruolo (Abbr.)'], start=2):
        ws.cell(3, c, t)
    for r, (area, turno, ruolo, sigla, *giorni) in enumerate(righe, start=4):
        ws.cell(r, 2, area)
        ws.cell(r, 4, turno or None)
        ws.cell(r, 5, ruolo)
        ws.cell(r, 6, sigla)
        for i, nome in enumerate(giorni):
            ws.cell(r, 7 + i, nome)
    cn = wb.create_sheet('Collegamento Nomi')
    cn['B3'], cn['C3'] = 'Nome nel Layout', 'Nome completo (Elenco Dipendenti)'
    for r, (breve, completo) in enumerate(nomi, start=4):
        cn.cell(r, 2, breve)
        cn.cell(r, 3, completo)
    wb.create_sheet('Calcoli')
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    buf.name = 'Organizzazione_Turni_con_Vista.xlsx'
    return buf


def riga(letta, nome):
    return next(r for r in letta.righe if r.nome == nome)


class LetturaLayoutTest(TestCase):
    def test_lunedi_dalla_vista(self):
        self.assertEqual(importa.lunedi_dal_file(file_layout()), LUNEDI)

    def test_posti_e_nomi_completi(self):
        letta = importa.leggi_file(file_layout(), LUNEDI)
        oddo = riga(letta, 'ODDO FEDERICO').turni[0]
        self.assertEqual((oddo.fascia, oddo.postazione, oddo.capoturno, oddo.ruolo), (Fascia.MATTINA, Postazione.IMP1, True, 'CT'))
        self.assertEqual(oddo.posto, 'Impianto 1 · Capo Turno')
        jarju = riga(letta, 'JARJU NABIE').turni[1]
        self.assertEqual((jarju.fascia, jarju.postazione, jarju.capoturno), (Fascia.MATTINA, Postazione.IMP1, False))
        self.assertEqual(riga(letta, 'JARJU NABIE').turni[2].fascia, Fascia.RIPOSO)

    def test_palista_impianto_non_ripetuto_sulla_pala(self):
        letta = importa.leggi_file(file_layout(), LUNEDI)
        titone = riga(letta, 'TITONE GIUSEPPE').turni[0]
        self.assertEqual((titone.postazione, titone.ruolo), (Postazione.IMP1, 'Pal'))
        self.assertEqual(titone.posto, 'Impianto 1 · Palista')

    def test_due_posti_nello_stesso_turno(self):
        letta = importa.leggi_file(file_layout(), LUNEDI)
        modello = riga(letta, 'MODELLO FRANCESCO').turni[0]
        self.assertEqual(modello.fascia, Fascia.POMERIGGIO)
        self.assertEqual(modello.posto, 'Impianto 1 · Palista + Sabbia - Sarco · Operatore di Linea')
        self.assertEqual(modello.incarichi, 'IMP1/Pal SABBIA/OdL')

    def test_chi_non_e_nel_layout_e_a_riposo_e_segnaposto_saltati(self):
        letta = importa.leggi_file(file_layout(), LUNEDI)
        nomi = [r.nome for r in letta.righe]
        self.assertIn('RALLO GASPARE', nomi)
        self.assertTrue(all(t.fascia == Fascia.RIPOSO for t in riga(letta, 'RALLO GASPARE').turni))
        self.assertNotIn('(SEGNAPOSTO)', nomi)
        self.assertNotIn('X', nomi)
        self.assertTrue(any('X' in a and 'saltate' in a for a in letta.avvisi))
        self.assertTrue(any('Ignoto' in a for a in letta.avvisi))
        ignoto = riga(letta, 'IGNOTO').turni[1]
        self.assertEqual(ignoto.postazione, Postazione.ROTOVAGLIO)

    def test_anteprima_in_sessione_conserva_il_posto(self):
        letta = importa.da_sessione(importa.in_sessione(importa.leggi_file(file_layout(), LUNEDI)))
        self.assertEqual(riga(letta, 'ODDO FEDERICO').turni[0].posto, 'Impianto 1 · Capo Turno')


class CaricamentoLayoutTest(TestCase):
    def setUp(self):
        self.ufficio = get_user_model().objects.create_user('uff', password='x', is_staff=True)
        Dipendente.objects.create(nome='ODDO FEDERICO')

    def test_carica_anteprima_e_pubblica(self):
        self.client.force_login(self.ufficio)
        r = self.client.post(reverse('turni:importa'), {'file': file_layout()})
        self.assertRedirects(r, reverse('turni:anteprima'))
        r = self.client.get(reverse('turni:anteprima'))
        self.assertContains(r, 'Impianto 1 · Capo Turno')
        self.client.post(reverse('turni:anteprima'))
        t = Turno.objects.get(dipendente__nome='ODDO FEDERICO', data=LUNEDI)
        self.assertEqual(t.descrizione, '1° turno · Impianto 1 · Capo Turno')
        self.assertEqual(t.nome_postazione, 'Impianto 1 · Capo Turno')
        self.assertTrue(t.capoturno)
        m = Turno.objects.get(dipendente__nome='MODELLO FRANCESCO', data=LUNEDI)
        self.assertIn('Sabbia - Sarco', m.descrizione)

    def test_ricaricare_aggiorna_senza_doppioni(self):
        importa.salva_settimana(importa.leggi_file(file_layout(), LUNEDI))
        righe = [list(r) for r in RIGHE]
        righe[1][4] = 'Rallo'  # lunedì Jarju sostituito da Rallo
        importa.salva_settimana(importa.leggi_file(file_layout(righe), LUNEDI))
        self.assertEqual(Turno.objects.get(dipendente__nome='JARJU NABIE', data=LUNEDI).fascia, Fascia.RIPOSO)
        self.assertEqual(Turno.objects.get(dipendente__nome='RALLO GASPARE', data=LUNEDI).posto, 'Impianto 1 · Operatore di Linea')
        self.assertEqual(Dipendente.objects.filter(nome__startswith='ODDO').count(), 1)


class AnteprimaTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('uff', password='x', is_staff=True))
        self.client.post(reverse('turni:importa'), {'file': file_layout()})

    def test_per_dipendente_in_ordine_alfabetico_con_le_sigle(self):
        r = self.client.get(reverse('turni:anteprima'))
        nomi = [x['nome'] for x in r.context['righe']]
        self.assertEqual(nomi, sorted(nomi))
        self.assertContains(r, '1T | Impianto 1 | CT')
        self.assertContains(r, '2T | Impianto 1 | Pal + Sabbia - Sarco')
        self.assertContains(r, 'Per Area')

    def test_per_area_come_il_layout(self):
        r = self.client.get(reverse('turni:anteprima') + '?vista=area')
        self.assertEqual(r.context['vista'], 'area')
        self.assertEqual([b['area'] for b in r.context['aree']][:2], ['Impianto 1', 'Piazzale - Pala'])
        self.assertContains(r, 'rowspan="3"')  # 1T dell'Impianto 1 su tre righe
