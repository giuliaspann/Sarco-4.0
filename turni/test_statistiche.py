import os
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AnalisiProdotto, Dipendente, ProdottoProduzione, ProduzioneTurno, RigaProduzione


def jpeg_finto():
    from io import BytesIO

    from PIL import Image

    b = BytesIO()
    Image.new('RGB', (40, 30), 'red').save(b, 'JPEG')
    return b.getvalue()


class StatisticheTest(TestCase):
    def setUp(self):
        self.op = get_user_model().objects.create_user('op', password='123456')
        Dipendente.objects.create(nome='ROSSI MARCO', utente=self.op)
        self.client.login(username='op', password='123456')
        patcher = mock.patch('pywebpush.webpush')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_barra_e_pagina(self):
        # dalla schermata Oggi si inseriscono produzione e analisi; l'elenco sta in Archivio
        r = self.client.get(reverse('turni:home'))
        for t in ('Dati produzione', 'Dati analisi', 'Archivio'):
            self.assertContains(r, t)
        self.assertContains(self.client.get(reverse('turni:archivio')), reverse('turni:statistiche'))
        r = self.client.get(reverse('turni:statistiche'))
        for t in ('Inserisci produzione del turno', 'Inserisci analisi prodotto', 'Report'):
            self.assertContains(r, t)

    def test_analisi_calcola_gt_e_limiti(self):
        oggi = timezone.localdate()
        r = self.client.post(reverse('turni:analisi_nuova'), {
            'campione': 'BIANCO', 'data': oggi.isoformat(), 'fascia': '1T', 'peso_kg': '20', 'numero': '57',
            'csp': '0,8', 'metallo': '0,1', 'foto': SimpleUploadedFile('a.jpg', jpeg_finto(), 'image/jpeg'),
        })
        a = AnalisiProdotto.objects.get()
        self.assertRedirects(r, reverse('turni:analisi', args=[a.pk]))
        csp = next(v for v in a.valori() if v['campo'] == 'csp')
        self.assertEqual(csp['gt'], Decimal('40'))  # 0,8 g su 20 kg = 40 g/t, oltre il limite di 25
        self.assertEqual([v['nome'] for v in a.fuori_limite], ['CSP'])
        from .models import Annuncio
        avviso = Annuncio.objects.get()  # fuori specifica: avviso importante in bacheca
        self.assertTrue(avviso.importante)
        self.assertIn('CSP 40 g/t (limite 25)', avviso.testo)
        self.assertTrue(a.foto)
        r = self.client.get(reverse('turni:report') + '?giorni=7')
        self.assertContains(r, 'Bianco')
        self.assertIn('CSP: 40 g/t (limite 25) ⚠️', r.context['testo'])

    def test_analisi_senza_valori(self):
        self.client.post(reverse('turni:analisi_nuova'), {'campione': 'BIANCO', 'data': timezone.localdate().isoformat()})
        self.assertFalse(AnalisiProdotto.objects.exists())

    def test_report_produzione(self):
        t = ProduzioneTurno.objects.create(data=timezone.localdate(), fascia='1T')
        p = ProdottoProduzione.objects.get(codice='A')
        RigaProduzione.objects.create(produzione=t, prodotto=p, tonnellate=Decimal('80.5'))
        r = self.client.get(reverse('turni:report'))
        self.assertIn('A Misto Imp. 1: 80.5 t (100.0%)', r.context['testo'])
        # righe dell'Impianto 2 come sul display: L-SCARTO1, M-SCARTO2, niente N
        imp2 = ProdottoProduzione.objects.filter(impianto='IMP2', attivo=True)
        self.assertEqual([p.codice for p in imp2], ['G', 'H', 'I', 'J', 'K', 'L', 'M'])
        self.assertEqual(imp2.get(codice='L').nome, 'Scarto 1')
        self.assertEqual(imp2.get(codice='M').categoria, ProdottoProduzione.Categoria.SCARTO)

    def test_leggi_foto(self):
        foto = lambda: SimpleUploadedFile('a.jpg', jpeg_finto(), 'image/jpeg')
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ANTHROPIC_API_KEY', None)
            self.assertNotContains(self.client.get(reverse('turni:analisi_nuova')), 'Leggi i numeri')
            self.assertEqual(self.client.post(reverse('turni:leggi_foto'), {'foto': foto()}).status_code, 503)
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-prova-0123456789abcdefghij'}):
            self.assertContains(self.client.get(reverse('turni:analisi_nuova')), 'Leggi i numeri')
            with mock.patch('turni.lettura.leggi_analisi', return_value={'peso_kg': 19.5, 'csp': 0.4, 'campione': 'BIANCO'}):
                j = self.client.post(reverse('turni:leggi_foto'), {'foto': foto(), 'tipo': 'analisi'}).json()
            self.assertEqual(j['campi'], {'peso_kg': '19,5', 'csp': '0,4', 'campione': 'BIANCO'})
            a = ProdottoProduzione.objects.get(codice='A')
            with mock.patch('turni.lettura.leggi_produzione_completa', return_value=({a.pk: 81.25}, None, None)):
                j = self.client.post(reverse('turni:leggi_foto'), {'foto': foto(), 'tipo': 'produzione'}).json()
            self.assertEqual(j['campi'], {f'p{a.pk}': '81,25'})
            # data e ora del display diventano giorno e turno (21:41 = 2° turno)
            with mock.patch('turni.lettura.leggi_produzione_completa', return_value=({a.pk: 81.25}, '2026-10-21', '21:41')):
                j = self.client.post(reverse('turni:leggi_foto'), {'foto': foto(), 'tipo': 'produzione'}).json()
            self.assertEqual((j['campi']['data'], j['campi']['fascia']), ('2026-10-21', '2T'))
