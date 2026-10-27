from datetime import date, time
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from . import saldi
from .models import AvvisoAssenza, Dipendente, Fascia, RichiestaFerie, RuoloApp, SaldoFerie, Settimana, Turno

LUNEDI = date(2026, 11, 2)


class SaldoReportTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.op = Dipendente.objects.create(nome='ROSSI MARIO', utente=User.objects.create_user('rossi', password='x'))
        self.dir = Dipendente.objects.create(nome='BIANCHI ANNA', ruolo_app=RuoloApp.DIREZIONE,
                                             utente=User.objects.create_user('bianchi', password='x'))
        s = Settimana.objects.create(lunedi=LUNEDI)
        for i in range(7):  # lavora lun-sab, domenica riposo
            Turno.objects.create(settimana=s, dipendente=self.op, data=date(2026, 11, 2 + i),
                                 fascia=Fascia.RIPOSO if i == 6 else Fascia.MATTINA, postazione='IMP1')
        SaldoFerie.objects.create(dipendente=self.op, al=date(2026, 9, 30), ferie_ore=100, rol_ore=20)
        p = mock.patch('turni.views_report.timezone.localdate', return_value=date(2026, 10, 30))
        p.start()
        self.addCleanup(p.stop)

    def test_saldo_meno_richieste_approvate(self):
        # sabato lavora, domenica no: dal lunedì alla domenica sono 6 giornate
        RichiestaFerie.objects.create(dipendente=self.op, tipo='FERIE', dal=LUNEDI, al=date(2026, 11, 8), stato='APPROVATA')
        RichiestaFerie.objects.create(dipendente=self.op, tipo='PERMESSO', dal=LUNEDI, al=LUNEDI,
                                      dalle=time(8), alle=time(10, 30), stato='APPROVATA')
        RichiestaFerie.objects.create(dipendente=self.op, tipo='PERMESSO', dal=LUNEDI, al=LUNEDI,
                                      dalle=time(8), alle=time(9), stato='ATTESA')
        # prima della data del saldo: già conteggiata nel saldo
        RichiestaFerie.objects.create(dipendente=self.op, tipo='FERIE', dal=date(2026, 9, 1), al=date(2026, 9, 5), stato='APPROVATA')
        r = saldi.residuo(self.op)
        self.assertEqual((r['ferie'], r['rol'], r['attesa_rol']), (Decimal('52'), Decimal('17.5'), Decimal('1')))
        self.client.login(username='rossi', password='x')
        pagina = self.client.get(reverse('turni:miei_turni'))
        self.assertContains(pagina, 'Ferie residue')
        self.assertContains(pagina, '6,5 giorni')

    def test_storico_solo_il_proprio(self):
        AvvisoAssenza.objects.create(dipendente=self.op, data=date(2026, 10, 1), tipo='RITARDO', alle=time(6, 30))
        AvvisoAssenza.objects.create(dipendente=self.dir, data=date(2026, 10, 1), tipo='MALATTIA', nota='segreta')
        self.client.login(username='rossi', password='x')
        r = self.client.get(reverse('turni:storico_assenze') + f'?anno=2026&dip={self.dir.pk}')
        self.assertContains(r, 'entra alle 6:30')
        self.assertNotContains(r, 'segreta')
        self.assertEqual(self.client.get(reverse('turni:report_assenze')).status_code, 403)

    def test_report_per_la_direzione(self):
        AvvisoAssenza.objects.create(dipendente=self.op, data=LUNEDI, tipo='MALATTIA')
        self.client.login(username='bianchi', password='x')
        r = self.client.get(reverse('turni:report_assenze') + '?periodo=prossime')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Rossi Mario')
        self.assertContains(r, '🤒 1 malattia')
        r = self.client.get(reverse('turni:storico_assenze') + f'?anno=2026&dip={self.op.pk}')
        self.assertContains(r, 'Rossi Mario')
