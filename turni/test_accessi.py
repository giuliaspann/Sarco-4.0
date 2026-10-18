"""Primo accesso: PIN generato dall'app, tessere, invio all'ufficio turni."""

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from . import accessi
from .models import Dipendente


class PinTest(TestCase):
    def test_pin_lungo_casuale_e_mai_debole(self):
        visti = set()
        for _ in range(300):
            pin = accessi.genera_pin()
            self.assertEqual(len(pin), 8)
            self.assertTrue(pin.isdigit())
            self.assertFalse(accessi._pin_debole(pin))
            visti.add(pin)
        self.assertGreater(len(visti), 295)  # non si ripetono
        for debole in ('00000000', '11111111', '12345678', '87654321', '23456789', '12121212'):
            self.assertTrue(accessi._pin_debole(debole), debole)


@override_settings(
    UFFICIO_TURNI_EMAIL='turni@azienda.test',
    EMAIL_HOST='smtp.azienda.test',
    RESEND_API_KEY='',
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class TessereTest(TestCase):
    def setUp(self):
        Dipendente.objects.all().delete()  # i profili dell'organigramma (migrazione 0012) non servono qui
        get_user_model().objects.create_user('ufficio', password='Password-Lunga-1', is_staff=True)
        self.client.login(username='ufficio', password='Password-Lunga-1')
        self.a = Dipendente.objects.create(nome='ROSSI MARIO')
        self.b = Dipendente.objects.create(nome='VERDI LUCA')

    def test_accesso_per_tutti_email_e_tessere_una_volta_sola(self):
        r = self.client.post(reverse('turni:dipendenti'), {'azione': 'pin_tutti'}, follow=True)
        self.assertContains(r, 'Credenziali inviate a')
        self.assertContains(r, 'rossi.mario')
        self.assertEqual(r['Cache-Control'], 'no-store')
        # email all'ufficio turni con nome utente e PIN di entrambi
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['turni@azienda.test'])
        self.assertIn('rossi.mario', mail.outbox[0].body)
        self.assertIn('verdi.luca', mail.outbox[0].body)
        # il PIN della tessera funziona e nel database c'è solo l'impronta
        pin = r.context['credenziali'][0]['pin']
        self.a.refresh_from_db()
        self.assertNotIn(pin, self.a.utente.password)
        self.assertTrue(self.a.utente.check_password(pin))
        # la pagina delle tessere non si può riaprire: i PIN non sono conservati
        self.assertRedirects(self.client.get(reverse('turni:credenziali')), reverse('turni:dipendenti'))

    def test_nuovo_pin_disattiva_quello_vecchio(self):
        self.client.post(reverse('turni:dipendenti'), {'dipendente': self.a.pk, 'azione': 'pin'})
        self.a.refresh_from_db()
        vecchio_hash = self.a.utente.password
        r = self.client.post(reverse('turni:dipendenti'), {'dipendente': self.a.pk, 'azione': 'pin'}, follow=True)
        nuovo = r.context['credenziali'][0]['pin']
        self.a.utente.refresh_from_db()
        self.assertNotEqual(vecchio_hash, self.a.utente.password)
        self.assertTrue(self.a.utente.check_password(nuovo))

    @override_settings(UFFICIO_TURNI_EMAIL='')
    def test_senza_email_configurata_si_vedono_solo_le_tessere(self):
        r = self.client.post(reverse('turni:dipendenti'), {'dipendente': self.a.pk, 'azione': 'pin'}, follow=True)
        self.assertContains(r, 'non è configurato')
        self.assertEqual(len(mail.outbox), 0)

    def test_qr_porta_al_login_con_nome_gia_scritto(self):
        r = self.client.post(reverse('turni:dipendenti'), {'dipendente': self.a.pk, 'azione': 'pin'}, follow=True)
        c = r.context['credenziali'][0]
        self.assertTrue(c['qr'].startswith('data:image/svg+xml'))
        self.assertTrue(c['link'].endswith('/turni/accesso/?u=rossi.mario'))
        self.client.logout()
        r = self.client.get(reverse('turni:login') + '?u=rossi.mario')
        self.assertContains(r, 'value="rossi.mario"')

    def test_solo_ufficio_crea_accessi(self):
        self.client.logout()
        d = Dipendente.objects.create(nome='BIANCHI PIO')
        d.utente = get_user_model().objects.create_user('bianchi', password='12345678')
        d.save()
        self.client.login(username='bianchi', password='12345678')
        self.client.post(reverse('turni:dipendenti'), {'azione': 'pin_tutti'})
        self.assertIsNone(Dipendente.objects.get(pk=self.a.pk).utente)
