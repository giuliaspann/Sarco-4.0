"""Sarco Workspace su PC, Fase 1: la home «Oggi in Sarco» con il menu e Ctrl K (24/11/2026)."""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (AvvisoAssenza, Dipendente, FermoImpianto, ProdottoProduzione, ProduzioneTurno, RigaProduzione)


class PlanciaPC(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ufficio = User.objects.create_user('giulia', password='x', first_name='Giulia')
        cls.ufficio.user_permissions.add(Permission.objects.get(codename='approva_richieste'))
        Dipendente.objects.create(nome='SPANO GIULIA', utente=cls.ufficio, ruolo_app='RESP_TURNI')
        cls.operaio = User.objects.create_user('operaio', password='x')
        cls.dip = Dipendente.objects.create(nome='ROSSI MARIO', utente=cls.operaio)
        # impiegato con mansione Ufficio, senza il permesso di approvare
        cls.impiegato = User.objects.create_user('impiegato', password='x')
        Dipendente.objects.create(nome='BIANCHI ANNA', utente=cls.impiegato, mansione='UFFICIO')

    def test_serve_accesso(self):
        r = self.client.get(reverse('turni:pc'))
        self.assertEqual(r.status_code, 302)

    def test_operai_tornano_al_telefono(self):
        self.client.force_login(self.operaio)
        r = self.client.get(reverse('turni:pc'))
        self.assertRedirects(r, reverse('turni:home'), fetch_redirect_response=False)

    def test_ufficio_vede_la_plancia(self):
        self.client.force_login(self.impiegato)
        r = self.client.get(reverse('turni:pc'))
        self.assertContains(r, 'Oggi in Sarco')
        self.assertContains(r, 'Ctrl K')
        self.assertContains(r, 'Impianto 1')
        self.assertContains(r, 'Nessuna produzione ancora inserita oggi')

    def test_numeri_veri(self):
        oggi = timezone.localdate()
        p = ProduzioneTurno.objects.create(data=oggi, fascia='1T')
        a = ProdottoProduzione.objects.create(codice='A', nome='MISTO', impianto='IMP1')
        b = ProdottoProduzione.objects.create(codice='E', nome='BARROTTI', impianto='IMP2')
        s = ProdottoProduzione.objects.create(codice='S', nome='SCARTO', impianto='IMP1', categoria='SCARTO')
        RigaProduzione.objects.create(produzione=p, prodotto=a, tonnellate=Decimal('1186'))
        RigaProduzione.objects.create(produzione=p, prodotto=b, tonnellate=Decimal('142'))
        RigaProduzione.objects.create(produzione=p, prodotto=s, tonnellate=Decimal('50'))  # lo scarto non conta
        FermoImpianto.objects.create(impianto='IMP2', causa='NASTRO', fermo_dal=timezone.now() - timedelta(minutes=30))
        self.client.force_login(self.ufficio)
        r = self.client.get(reverse('turni:pc'))
        self.assertContains(r, '1.328<small> t</small>', html=False)
        self.assertContains(r, 'Imp. 1 1.186 t · Imp. 2 142 t')
        self.assertContains(r, 'Fermo da 30 min')
        self.assertContains(r, 'Rottura nastro')

    def test_da_approvare_con_tasti(self):
        AvvisoAssenza.objects.create(dipendente=self.dip, tipo=AvvisoAssenza._meta.get_field('tipo').choices[0][0],
                                     data=timezone.localdate())
        self.client.force_login(self.ufficio)
        r = self.client.get(reverse('turni:pc'))
        self.assertContains(r, 'Approva')
        self.assertContains(r, 'class="pc-conta">1<')
        # chi è dell'ufficio ma non approva vede la richiesta con il solo tasto Apri
        self.client.force_login(self.impiegato)
        r = self.client.get(reverse('turni:pc'))
        self.assertNotContains(r, '>Approva<')
        self.assertContains(r, '>Apri<')
