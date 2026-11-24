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


class DaApprovarePC(TestCase):
    """Da approvare su PC: elenco a sinistra, dettaglio a destra, Approva/Rifiuta con la nota (proposta B)."""

    @classmethod
    def setUpTestData(cls):
        cls.ufficio = User.objects.create_user('giulia', password='x', first_name='Giulia')
        cls.ufficio.user_permissions.add(Permission.objects.get(codename='approva_richieste'))
        Dipendente.objects.create(nome='SPANO GIULIA', utente=cls.ufficio, ruolo_app='RESP_TURNI')
        cls.impiegato = User.objects.create_user('impiegato', password='x')
        Dipendente.objects.create(nome='BIANCHI ANNA', utente=cls.impiegato, mansione='UFFICIO')
        cls.operaio = User.objects.create_user('operaio', password='x')
        cls.dip = Dipendente.objects.create(nome='ROSSI MARIO', utente=cls.operaio)

    def setUp(self):
        self.avviso = AvvisoAssenza.objects.create(dipendente=self.dip, tipo='RITARDO', data=timezone.localdate(), nota='Visita medica')

    def test_elenco_e_dettaglio(self):
        self.client.force_login(self.ufficio)
        r = self.client.get(reverse('turni:pc_richieste'))
        self.assertContains(r, '1 in attesa')
        self.assertContains(r, 'Rossi Mario')
        self.assertContains(r, '«Visita medica»')
        self.assertContains(r, 'Nessun altro collega assente quel giorno')
        self.assertContains(r, 'name="nota"')

    def test_approva_con_nota(self):
        self.client.force_login(self.ufficio)
        r = self.client.post(reverse('turni:pc_richieste'), {'tipo': 'avviso', 'pk': self.avviso.pk, 'scelta': 'approva',
                                                             'nota': 'Ok, avvisa il CT'})
        self.assertRedirects(r, reverse('turni:pc_richieste'), fetch_redirect_response=False)
        self.avviso.refresh_from_db()
        self.assertEqual((self.avviso.esito, self.avviso.nota_ufficio, self.avviso.visto_da), ('approvato', 'Ok, avvisa il CT', self.ufficio))
        r = self.client.get(reverse('turni:pc_richieste') + '?vista=decise')
        self.assertContains(r, 'Approvato')

    def test_dalla_plancia_si_torna_alla_plancia(self):
        self.client.force_login(self.ufficio)
        r = self.client.post(reverse('turni:pc_richieste'), {'tipo': 'avviso', 'pk': self.avviso.pk, 'scelta': 'rifiuta', 'torna': 'plancia'})
        self.assertRedirects(r, reverse('turni:pc'), fetch_redirect_response=False)
        self.avviso.refresh_from_db()
        self.assertEqual(self.avviso.esito, 'rifiutato')

    def test_chi_non_approva_vede_ma_non_decide(self):
        self.client.force_login(self.impiegato)
        r = self.client.get(reverse('turni:pc_richieste'))
        self.assertContains(r, 'Questa richiesta la decide l')
        self.assertNotContains(r, 'name="nota"')
        r = self.client.post(reverse('turni:pc_richieste'), {'tipo': 'avviso', 'pk': self.avviso.pk, 'scelta': 'approva'})
        self.assertEqual(r.status_code, 403)
        self.avviso.refresh_from_db()
        self.assertEqual(self.avviso.esito, '')

    def test_operai_no(self):
        self.client.force_login(self.operaio)
        r = self.client.get(reverse('turni:pc_richieste'))
        self.assertRedirects(r, reverse('turni:home'), fetch_redirect_response=False)


class TurniPC(TestCase):
    """Turni su PC: Layout turni per area (proposta B), griglia per dipendente, pannello dell'ufficio."""

    @classmethod
    def setUpTestData(cls):
        from .models import Settimana, Turno
        cls.ufficio = User.objects.create_user('giulia', password='x', is_staff=True)
        cls.operaio = User.objects.create_user('operaio', password='x')
        dip = Dipendente.objects.create(nome='ROSSI MARIO', utente=cls.operaio)
        oggi = timezone.localdate()
        lunedi = oggi - timedelta(days=oggi.weekday())
        s = Settimana.objects.create(lunedi=lunedi)
        Turno.objects.create(settimana=s, dipendente=dip, data=oggi, fascia='1T', postazione='IMP1', ruolo='OdL',
                             posto='Impianto 1 · Operatore di Linea', incarichi='IMP1/OdL')

    def test_per_area_e_pannello(self):
        self.client.force_login(self.ufficio)
        r = self.client.get(reverse('turni:pc_turni'))
        self.assertContains(r, 'Layout turni')
        self.assertContains(r, 'Impianto 1')
        self.assertContains(r, 'Rossi')
        self.assertContains(r, 'Scegli il file Excel')
        self.assertContains(r, 'Nessun turno extra aperto.')

    def test_per_dipendente_e_ricerca(self):
        self.client.force_login(self.ufficio)
        r = self.client.get(reverse('turni:pc_turni') + '?vista=dipendente')
        self.assertContains(r, '<b>Rossi</b> Mario', html=False)
        self.assertContains(r, '1T · Imp 1')
        r = self.client.get(reverse('turni:pc_turni') + '?vista=dipendente&q=bianchi')
        self.assertContains(r, 'Nessun dipendente con')

    def test_operai_no(self):
        self.client.force_login(self.operaio)
        self.assertRedirects(self.client.get(reverse('turni:pc_turni')), reverse('turni:home'), fetch_redirect_response=False)
