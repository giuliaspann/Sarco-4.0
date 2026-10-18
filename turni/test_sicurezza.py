"""Controlli di sicurezza: accessi, permessi, intestazioni, file caricati."""

from datetime import date, timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import AvvisoAssenza, BloccoAccesso, Dipendente, Pulizia, Settimana, Turno, ElementoPulizia


class AccessiTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.ufficio = User.objects.create_user('ufficio', password='Password-Lunga-1', is_staff=True, is_superuser=True)
        d = Dipendente.objects.create(nome='ROSSI MARIO')
        d.utente = User.objects.create_user('rossi', password='12345678')
        d.save()

    def test_blocco_anche_per_ufficio_e_nomi_inesistenti(self):
        url = reverse('turni:login')
        for _ in range(5):
            self.client.post(url, {'username': 'ufficio', 'password': 'sbagliata'})
        r = self.client.post(url, {'username': 'ufficio', 'password': 'Password-Lunga-1'})
        self.assertContains(r, 'Troppi tentativi')
        # stesso messaggio per un nome che non esiste: non si capisce chi è registrato
        for _ in range(5):
            self.client.post(url, {'username': 'nessuno', 'password': 'x'})
        self.assertContains(self.client.post(url, {'username': 'nessuno', 'password': 'x'}), 'Troppi tentativi')

    def test_blocco_per_indirizzo_di_rete(self):
        url = reverse('turni:login')
        for i in range(20):  # nomi diversi dallo stesso indirizzo
            self.client.post(url, {'username': f'prova{i}', 'password': 'x'}, REMOTE_ADDR='10.0.0.9')
        r = self.client.post(url, {'username': 'rossi', 'password': '12345678'}, REMOTE_ADDR='10.0.0.9')
        self.assertContains(r, 'Troppi tentativi')
        # da un altro indirizzo si entra
        r = self.client.post(url, {'username': 'rossi', 'password': '12345678'}, REMOTE_ADDR='10.0.0.10')
        self.assertEqual(r.status_code, 302)

    def test_blocco_anche_sul_pannello_admin(self):
        url = reverse('admin:login')
        for _ in range(5):
            self.client.post(url, {'username': 'ufficio', 'password': 'sbagliata'})
        r = self.client.post(url, {'username': 'ufficio', 'password': 'Password-Lunga-1'})
        self.assertContains(r, 'Troppi tentativi')

    def test_accesso_riuscito_azzera_gli_errori(self):
        url = reverse('turni:login')
        for _ in range(3):
            self.client.post(url, {'username': 'rossi', 'password': 'no'})
        self.client.post(url, {'username': 'rossi', 'password': '12345678'})
        self.assertFalse(BloccoAccesso.objects.filter(chiave='u:rossi').exists())


class PermessiTest(TestCase):
    """Ogni pagina riservata respinge chi non ha il diritto di vederla."""

    def setUp(self):
        User = get_user_model()
        lun = date(2026, 10, 12)
        s = Settimana.objects.create(lunedi=lun)
        self.a = Dipendente.objects.create(nome='ROSSI MARIO', utente=User.objects.create_user('a', password='12345678'))
        self.b = Dipendente.objects.create(nome='VERDI LUCA', utente=User.objects.create_user('b', password='12345678'))
        self.turno_a = Turno.objects.create(settimana=s, dipendente=self.a, data=lun, fascia='1T')
        el = ElementoPulizia.objects.create(nome='Nastro', tipo='ZONA')
        self.pulizia_a = Pulizia.objects.create(turno=self.turno_a, elemento=el)
        self.avviso_a = AvvisoAssenza.objects.create(dipendente=self.a, data=lun, tipo='MALATTIA', nota='riservato')

    def test_pagine_ufficio_vietate_agli_operai(self):
        self.client.login(username='b', password='12345678')
        for nome in ('importa', 'dipendenti', 'ufficio_richieste', 'ufficio_extra'):
            r = self.client.get(reverse(f'turni:{nome}'))
            self.assertIn(r.status_code, (302, 403), nome)
        self.assertNotEqual(self.client.get('/admin/').status_code, 200)

    def test_dati_di_un_collega_non_accessibili(self):
        self.client.login(username='b', password='12345678')
        self.assertEqual(self.client.get(reverse('turni:pulizie_turno', args=[self.turno_a.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('turni:foto', args=[self.pulizia_a.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('turni:capoturno')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('turni:richieste')), 'riservato')

    def test_senza_accesso_si_va_al_login(self):
        for nome in ('home', 'miei_turni', 'squadra', 'settimana_tutti', 'pulizie', 'richieste', 'messaggi', 'chat_nuovi'):
            r = self.client.get(reverse(f'turni:{nome}'))
            self.assertEqual(r.status_code, 302, nome)
            self.assertIn('/turni/accesso/', r['Location'])


class IntestazioniTest(TestCase):
    def test_intestazioni_di_sicurezza(self):
        r = self.client.get(reverse('turni:login'))
        self.assertIn("frame-ancestors 'none'", r['Content-Security-Policy'])
        self.assertIn("script-src 'self'", r['Content-Security-Policy'])
        self.assertNotIn('unsafe-inline', r['Content-Security-Policy'])
        self.assertEqual(r['X-Frame-Options'], 'DENY')
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(r['Referrer-Policy'], 'same-origin')

    def test_nessuno_stile_o_script_inline_nelle_pagine(self):
        User = get_user_model()
        d = Dipendente.objects.create(nome='ROSSI MARIO', utente=User.objects.create_user('a', password='12345678'))
        self.client.login(username='a', password='12345678')
        for nome in ('home', 'miei_turni', 'pulizie', 'richieste', 'messaggi', 'settimana_tutti', 'squadra'):
            html = self.client.get(reverse(f'turni:{nome}')).content.decode()
            self.assertNotIn(' style="', html, nome)
            self.assertNotIn(' onclick=', html, nome)
            self.assertNotIn('<script>', html, nome)


class CaricamentiTest(TestCase):
    def test_excel_troppo_grande_rifiutato(self):
        get_user_model().objects.create_user('ufficio', password='x', is_staff=True)
        self.client.login(username='ufficio', password='x')
        grande = SimpleUploadedFile('DAL 12-10-2026.xlsx', b'0' * (5 * 1024 * 1024 + 1))
        r = self.client.post(reverse('turni:importa'), {'file': grande})
        self.assertContains(r, 'troppo grande')
