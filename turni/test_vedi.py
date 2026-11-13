"""Ritocchi del 13/11/2026: PDF e foto con il tasto indietro, Archivio senza foto in alto, nome per esteso nella home."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Dipendente


class VediTest(TestCase):
    def setUp(self):
        self.d = Dipendente.objects.create(nome='VALENTI MASSIMO')
        self.d.utente = get_user_model().objects.create_user('valenti.massimo')
        self.d.save()
        self.client.force_login(self.d.utente)

    def test_pdf_e_foto_nella_pagina_con_il_tasto_indietro(self):
        r = self.client.get(reverse('turni:vedi'), {'u': '/turni/archivio/pulizie/pdf/'})
        self.assertContains(r, 'class="vd-pdf"')
        self.assertContains(r, 'dentro=1')
        self.assertContains(r, 'data-indietro')
        self.assertContains(r, 'Salva, stampa o invia')
        r = self.client.get(reverse('turni:vedi'), {'u': '/turni/foto/3/'})
        self.assertContains(r, 'class="vd-foto"')

    def test_solo_indirizzi_dell_app(self):
        for u in ('https://esempio.it/x.pdf', '//esempio.it/x', '/admin/', '/turni//x', ''):
            self.assertEqual(self.client.get(reverse('turni:vedi'), {'u': u}).status_code, 404, u)

    def test_il_pdf_si_mostra_solo_dentro_l_app(self):
        r = self.client.get(reverse('turni:archivio_pdf', args=['pulizie']), {'dentro': '1'})
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertTrue(r['Content-Disposition'].startswith('inline'))
        self.assertEqual(r['X-Frame-Options'], 'SAMEORIGIN')
        self.assertEqual(r['Content-Security-Policy'], "frame-ancestors 'self'")
        r = self.client.get(reverse('turni:archivio_pdf', args=['pulizie']))
        self.assertTrue(r['Content-Disposition'].startswith('attachment'))
        # le pagine normali restano non incorniciabili
        self.assertIn("frame-ancestors 'none'", self.client.get(reverse('turni:archivio'))['Content-Security-Policy'])

    def test_archivio_senza_foto_e_nome_per_esteso_in_home(self):
        r = self.client.get(reverse('turni:archivio'))
        self.assertNotContains(r, 'ig-griglia-foto')
        self.assertContains(r, reverse('turni:archivio_pulizie'))
        self.assertContains(self.client.get(reverse('turni:home')), 'Valenti Massimo')
