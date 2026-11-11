from datetime import datetime, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import importa
from . import richieste as svc
from .models import AvvisoAssenza, Dipendente, Disponibilita, Fascia, Postazione, Turno, TurnoExtra
from .tests import LUNEDI, RIGHE, file_turni

DOMENICA = LUNEDI + timedelta(days=6)


class BaseTest(TestCase):
    """Settimana del 12/10, "oggi" è lunedì alle 8. Domenica: Spano festa, Drame riposo, Crimi 1T palista."""

    def setUp(self):
        importa.salva_settimana(importa.leggi_file(file_turni(RIGHE), LUNEDI))
        User = get_user_model()
        for nome, user in [("SPANO' A. MAURO", 'spano'), ('DRAME BOUBA', 'drame'), ('CRIMI BENITO', 'crimi')]:
            d = Dipendente.objects.get(nome=nome)
            d.utente = User.objects.create_user(user, password='123456')
            d.save()
        self.spano = Dipendente.objects.get(nome="SPANO' A. MAURO")
        self.drame = Dipendente.objects.get(nome='DRAME BOUBA')
        self.crimi = Dipendente.objects.get(nome='CRIMI BENITO')
        self.resp = User.objects.create_user('resp', password='x')
        self.resp.user_permissions.add(Permission.objects.get(codename='approva_richieste'))
        adesso = timezone.make_aware(datetime.combine(LUNEDI, datetime.min.time()) + timedelta(hours=8))
        patcher = mock.patch('django.utils.timezone.now', return_value=adesso)
        patcher.start()
        self.addCleanup(patcher.stop)


class TurnoExtraTest(BaseTest):
    def crea(self, posti=1):
        self.client.login(username='resp', password='x')
        self.client.post(
            reverse('turni:ufficio_extra'),
            {'azione': 'crea', 'data': DOMENICA, 'fascia': '1T', 'postazione': 'IMP1', 'posti': posti, 'nota': 'serve aiuto'},
        )
        return TurnoExtra.objects.get()

    def test_volontari_e_conferma(self):
        extra = self.crea()

        # lo vedono solo i liberi quel giorno
        self.assertEqual([e.pk for e in svc.extra_per(self.drame)], [extra.pk])
        self.assertEqual(svc.extra_per(self.crimi), [])
        self.client.login(username='drame', password='123456')
        self.assertContains(self.client.get(reverse('turni:miei_turni')), 'Sono disponibile')

        # il primo che risponde copre il posto: il turno entra subito nel suo calendario (Giulia, 11/11)
        self.client.login(username='drame', password='123456')
        self.client.post(reverse('turni:rispondi_extra', args=[extra.pk]), {'azione': 'offri'})
        turno = Turno.objects.get(dipendente=self.drame, data=DOMENICA)
        self.assertEqual((turno.fascia, turno.postazione), (Fascia.MATTINA, Postazione.IMP1))
        self.assertIn('extra', turno.nota_modifica)
        extra.refresh_from_db()
        self.assertTrue(extra.chiusa)  # un posto solo: coperto
        # l'ufficio riceve la notifica
        from .models import Notifica
        self.assertTrue(Notifica.objects.filter(utente__username='resp', titolo__contains='disponibile').exists())

        # posti finiti: Spano non può più offrirsi, e Drame non si ritira da solo
        self.client.login(username='spano', password='123456')
        self.client.post(reverse('turni:rispondi_extra', args=[extra.pk]), {'azione': 'offri'})
        self.assertFalse(Disponibilita.objects.filter(dipendente=self.spano).exists())
        with self.assertRaises(svc.RichiestaNonValida):
            svc.ritira(extra, self.drame)

        # ricaricare l'Excel non toglie il turno extra
        importa.salva_settimana(importa.leggi_file(file_turni(RIGHE), LUNEDI))
        self.assertEqual(Turno.objects.get(dipendente=self.drame, data=DOMENICA).fascia, Fascia.MATTINA)

    def test_ritirarsi_prima_della_conferma(self):
        extra = self.crea()
        svc.offri(extra, self.drame)
        svc.ritira(extra, self.drame)
        self.assertFalse(extra.disponibilita.exists())

    def test_settimana_non_caricata(self):
        extra = TurnoExtra.objects.create(data=LUNEDI + timedelta(days=13), fascia='1T')
        disp = Disponibilita.objects.create(extra=extra, dipendente=self.drame)
        with self.assertRaises(svc.RichiestaNonValida):
            svc.conferma_volontario(disp)

    def test_solo_il_responsabile_gestisce(self):
        self.client.login(username='crimi', password='123456')
        self.assertEqual(self.client.get(reverse('turni:ufficio_extra')).status_code, 403)


class AvvisoTest(BaseTest):
    def test_avviso_visto_da_ufficio_e_capoturno_non_dai_colleghi(self):
        martedi = LUNEDI + timedelta(days=1)  # Crimi è Capo Turno di notte martedì
        self.client.login(username='drame', password='123456')
        # la malattia non si segnala più dall'app (10/11/2026)
        r = self.client.post(reverse('turni:nuovo_avviso'), {'tipo': 'MALATTIA', 'data': martedi, 'nota': 'febbre'})
        self.assertContains(r, 'Scegli il tipo di avviso')
        self.assertNotContains(r, 'value="MALATTIA"')
        self.assertFalse(AvvisoAssenza.objects.exists())
        r = self.client.post(
            reverse('turni:nuovo_avviso'), {'tipo': 'ALTRO', 'data': martedi, 'nota': 'visita medica'}, follow=True
        )
        self.assertContains(r, 'Avviso inviato')
        avviso = AvvisoAssenza.objects.get()

        # il Capo Turno lo vede nella Verifica di quel giorno
        self.client.login(username='crimi', password='123456')
        r = self.client.get(reverse('turni:capoturno'), {'giorno': martedi})
        self.assertContains(r, 'visita medica')
        # un collega che non è Capo Turno quel giorno no
        self.client.login(username='spano', password='123456')
        self.assertEqual(self.client.get(reverse('turni:capoturno'), {'giorno': LUNEDI + timedelta(days=5)}).status_code, 403)
        self.assertNotContains(self.client.get(reverse('turni:miei_turni')), 'visita medica')

        # l'ufficio lo vede e lo segna come visto
        self.client.login(username='resp', password='x')
        self.assertContains(self.client.get(reverse('turni:ufficio_richiesta', args=['avviso', avviso.pk])), 'visita medica')
        # prima chiede di convalidare la scelta, poi la esegue
        self.assertContains(self.client.get(reverse('turni:ufficio_richiesta_scelta', args=['avviso', avviso.pk, 'approva'])), 'Sì, approva')
        self.client.post(reverse('turni:ufficio_richiesta_scelta', args=['avviso', avviso.pk, 'approva']))
        avviso.refresh_from_db()
        self.assertIsNotNone(avviso.visto_il)
        self.assertEqual(avviso.esito, 'approvato')


class RuoloExtraTest(BaseTest):
    def test_richiesta_per_manutentore_e_palista(self):
        from .models import Mansione

        manut = TurnoExtra.objects.create(data=DOMENICA, fascia='1T', ruolo=Mansione.MANUTENTORE)
        pala = TurnoExtra.objects.create(data=DOMENICA, fascia='1T', ruolo=Mansione.PALISTA)
        # Drame non è manutentore né ha fatto il palista: vede nessuna delle due
        self.assertEqual(svc.extra_per(self.drame), [])
        with self.assertRaises(svc.RichiestaNonValida):
            svc.offri(manut, self.drame)
        # l'ufficio lo segna manutentore dalla pagina Dipendenti
        get_user_model().objects.create_user('uff', password='x', is_staff=True)
        self.client.login(username='uff', password='x')
        self.client.post(reverse('turni:dipendenti'), {'dipendente': self.drame.pk, 'azione': 'mansione', 'mansione': 'MANUTENTORE'})
        self.drame.refresh_from_db()
        self.assertEqual([e.pk for e in svc.extra_per(self.drame)], [manut.pk])
        # Crimi ha fatto il palista questa settimana: vede la richiesta per palista anche senza mansione impostata
        Turno.objects.filter(dipendente=self.crimi, data=DOMENICA).update(fascia=Fascia.RIPOSO, postazione='')
        self.assertEqual([e.pk for e in svc.extra_per(self.crimi)], [pala.pk])
        svc.offri(pala, self.crimi)
        svc.conferma_volontario(Disponibilita.objects.get(extra=pala))
        self.assertEqual(Turno.objects.get(dipendente=self.crimi, data=DOMENICA).postazione, Postazione.PALISTA)
