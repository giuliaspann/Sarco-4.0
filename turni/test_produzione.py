from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Dipendente, FermoImpianto, IscrizionePush, ProdottoProduzione, ProduzioneTurno, RigaProduzione


class ProduzioneTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.operaio = User.objects.create_user('operaio', password='123456')
        Dipendente.objects.create(nome='ROSSI MARCO', utente=self.operaio)
        self.marchese = User.objects.create_user('marchese', password='123456')
        d = Dipendente.objects.get(nome='MARCHESE LEONARDO')
        d.utente = self.marchese
        d.save()
        IscrizionePush.objects.create(utente=self.marchese, endpoint='https://fcm.googleapis.com/fcm/send/m', p256dh='k', auth='a')
        patcher = mock.patch('pywebpush.webpush')
        self.webpush = patcher.start()
        self.addCleanup(patcher.stop)
        self.p = {p.nome: p for p in ProdottoProduzione.objects.filter(impianto='IMP1')}

    def turno(self, giorno, fascia, barrotti):
        t = ProduzioneTurno.objects.create(data=giorno, fascia=fascia)
        RigaProduzione.objects.create(produzione=t, prodotto=self.p['Misto Imp. 1'], tonnellate=100 - barrotti)
        RigaProduzione.objects.create(produzione=t, prodotto=self.p['Barrotti'], tonnellate=barrotti)
        return t

    def test_solo_responsabili_e_capi(self):
        self.client.login(username='operaio', password='123456')
        self.assertEqual(self.client.get(reverse('turni:produzione')).status_code, 403)

    def test_scarto_alto_segnalato(self):
        oggi = timezone.localdate()
        for n in range(1, 5):
            self.turno(oggi - timedelta(days=n), '1T', 6)  # media 6%
        self.client.login(username='marchese', password='123456')
        self.client.post(reverse('turni:produzione_nuova'), {
            'data': oggi.isoformat(), 'fascia': '2T',
            f"p{self.p['Misto Imp. 1'].pk}": '86', f"p{self.p['Barrotti'].pk}": '14,0',
        })
        t = ProduzioneTurno.objects.get(data=oggi, fascia='2T')
        self.assertEqual(t.righe.count(), 2)
        self.assertEqual(self.webpush.call_count, 0)  # chi inserisce è il responsabile stesso
        r = self.client.get(reverse('turni:produzione_turno', args=[t.pk]))
        barrotti = next(x for x in r.context['righe'] if x['r'].prodotto.nome == 'Barrotti')
        self.assertAlmostEqual(float(barrotti['perc']), 14.0)
        self.assertAlmostEqual(float(barrotti['media']), 6.0)
        self.assertTrue(barrotti['alto'])
        self.assertContains(self.client.get(reverse('turni:produzione')), 'Barrotti 14,0%')


class FermoCorrenteTest(TestCase):
    def test_fermo_gia_finito(self):
        u = get_user_model().objects.create_user('nino', password='123456')
        Dipendente.objects.create(nome='NINO', utente=u)
        self.client.login(username='nino', password='123456')
        oggi = timezone.localtime().date()
        self.client.post(reverse('turni:nuovo_fermo'), {
            'impianto': 'IMP1', 'causa': 'CORRENTE', 'dal': f'{oggi}T00:05', 'ripartito': f'{oggi}T00:26',
        })
        f = FermoImpianto.objects.get()
        self.assertFalse(f.in_corso)
        self.assertEqual((f.minuti, f.get_causa_display()), (21, 'Alimentazione esterna (corrente)'))
