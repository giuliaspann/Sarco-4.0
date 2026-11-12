"""Calendario D nel profilo (Giulia, 12/11/2026): settimana o mese con turno, area, CT, riunioni, visite, corsi,
scadenze, compleanni, fermi e giorni rossi. Ufficio e responsabile impianto vedono anche gli eventi di tutti."""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Dipendente, Scadenza, Settimana, Turno
from .views_calendario import festivi, pasqua

LUNEDI = date(2026, 11, 9)


class CalendarioDTest(TestCase):
    def setUp(self):
        U = get_user_model()
        self.uff = U.objects.create_user('uff', is_staff=True)
        self.oddo = Dipendente.objects.create(nome='ODDO SALVATORE', utente=U.objects.create_user('oddo'),
                                              data_nascita=date(1990, 11, 13))
        self.torre = Dipendente.objects.create(nome='TORRE VITO', utente=U.objects.create_user('torre'),
                                               data_nascita=date(1985, 11, 14))
        self.ri = Dipendente.objects.create(nome='RIZZO IVO', utente=U.objects.create_user('ri'), resp_impianto=True)
        self.rp = Dipendente.objects.create(nome='PIAZZA PIO', utente=U.objects.create_user('rp'), resp_piazzale=True)
        s = Settimana.objects.create(lunedi=LUNEDI)
        Turno.objects.create(settimana=s, dipendente=self.oddo, data=LUNEDI + timedelta(days=3), fascia='1T',
                             postazione='IMP1', capoturno=True)
        Turno.objects.create(settimana=s, dipendente=self.oddo, data=LUNEDI + timedelta(days=4), fascia='2T', postazione='SABBIA')
        Scadenza.objects.create(dipendente=self.oddo, tipo='VISITA', scade_il=LUNEDI + timedelta(days=2))
        Scadenza.objects.create(dipendente=self.torre, tipo='CORSO', scade_il=LUNEDI + timedelta(days=2), descrizione='antincendio')

    def test_feste_nazionali(self):
        self.assertEqual(pasqua(2026), date(2026, 4, 5))
        self.assertEqual(pasqua(2027), date(2027, 3, 28))
        f = festivi(2026)
        self.assertEqual(f[date(2026, 4, 6)], 'Pasquetta')
        self.assertEqual(f[date(2026, 10, 4)], 'San Francesco')
        self.assertEqual(len(f), 13)

    def test_profilo_si_apre_sulla_settimana_con_turno_area_e_ct(self):
        self.client.force_login(self.oddo.utente)
        r = self.client.get(reverse('turni:miei_turni'), {'settimana': LUNEDI.isoformat(), 'giorno': (LUNEDI + timedelta(days=2)).isoformat()})
        self.assertEqual(r.context['kd_vista'], 'settimana')
        pagina = r.content.decode()
        self.assertLess(pagina.index('>Settimana<'), pagina.index('>Mese<'))  # Settimana è il tasto a sinistra
        self.assertLess(pagina.index('>Calendario<'), pagina.index('>Turni di tutti<'))
        self.assertNotIn('>I miei turni<', pagina)
        self.assertNotIn('Eventi di tutti', pagina)
        for t in ('kd-ct', 'IMP 1', 'SABB.', '🎂 Torre V.', '🎂 Tu!', '🩺 Visita'):
            self.assertIn(t, pagina)
        self.assertNotIn('Corso', pagina)  # il corso di Torre lo vede solo l'ufficio

    def test_mese_mostra_ognissanti_rosso(self):
        self.client.force_login(self.oddo.utente)
        r = self.client.get(reverse('turni:miei_turni'), {'vista': 'mese', 'mese': '2026-11', 'giorno': '2026-11-01'})
        self.assertEqual(r.context['kd_vista'], 'mese')
        self.assertContains(r, 'Ognissanti')
        self.assertContains(r, 'kd-mese')

    def test_ufficio_vede_gli_eventi_di_tutti_e_puo_filtrarli(self):
        self.client.force_login(self.uff)
        url = reverse('turni:calendario')
        r = self.client.get(url, {'settimana': LUNEDI.isoformat()})
        for t in ('🩺 Oddo S.', '🎓 Torre V.', '<h1>Calendario</h1>'):
            self.assertContains(r, t)
        self.assertNotContains(r, 'Eventi di tutti')  # l'ufficio non ha la barra
        r = self.client.get(url, {'settimana': LUNEDI.isoformat(), 'via': 'visita'})
        self.assertNotContains(r, '🩺 Oddo S.')
        self.assertContains(r, '🎓 Torre V.')

    def test_ri_si_e_rp_no(self):
        self.client.force_login(self.ri.utente)
        self.assertContains(self.client.get(reverse('turni:miei_turni')), 'Eventi di tutti')
        r = self.client.get(reverse('turni:calendario'), {'settimana': LUNEDI.isoformat()})
        self.assertContains(r, '🩺 Oddo S.')
        self.client.force_login(self.rp.utente)
        self.assertNotContains(self.client.get(reverse('turni:miei_turni')), 'Eventi di tutti')
        self.assertEqual(self.client.get(reverse('turni:calendario')).status_code, 403)

    def test_turni_di_tutti_ha_la_stessa_barra(self):
        self.client.force_login(self.oddo.utente)
        pagina = self.client.get(reverse('turni:settimana_tutti')).content.decode()
        self.assertIn('ig-schede', pagina)
        self.assertLess(pagina.index('>Calendario<'), pagina.index('>Turni di tutti<'))
