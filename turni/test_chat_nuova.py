"""Chat (Giulia, 11/11/2026): foto, tondino con la foto, spunte blu, chi ha letto, sondaggi; foto profilo anche per l'ufficio."""

import shutil
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import Chat, Dipendente, LetturaChat, MessaggioChat, Sondaggio, VotoSondaggio

MEDIA = tempfile.mkdtemp()


def jpg():
    buf = BytesIO()
    Image.new('RGB', (80, 60), 'green').save(buf, 'JPEG')
    return SimpleUploadedFile('foto.jpg', buf.getvalue(), content_type='image/jpeg')


@override_settings(MEDIA_ROOT=MEDIA, PUSH_SINCRONO=True)
class ChatNuovaTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        U = get_user_model()
        self.chat = Chat.objects.create(nome='Prova chat', tutti=False)
        self.a = Dipendente.objects.create(nome='ROSSI MARIO', utente=U.objects.create_user('rossi', last_login=timezone.now()))
        self.b = Dipendente.objects.create(nome='VERDI ANNA', utente=U.objects.create_user('verdi', last_login=timezone.now()))
        self.chat.membri.add(self.a.utente, self.b.utente)
        self.url = reverse('turni:messaggi') + f'?vista=chat&chat={self.chat.pk}'

    def scrivi(self, **dati):
        return self.client.post(reverse('turni:messaggi'), {'vista': 'chat', 'chat': self.chat.pk, 'azione': 'chat', **dati})

    def test_foto_spunte_e_chi_ha_letto(self):
        self.client.force_login(self.a.utente)
        self.scrivi(testo='', foto=jpg())
        m = MessaggioChat.objects.get()
        self.assertTrue(m.foto)
        self.assertEqual(self.client.get(reverse('turni:foto_chat', args=[m.pk]))['Content-Type'], 'image/jpeg')
        pagina = self.client.get(self.url).content.decode()
        self.assertIn('wa-spunte', pagina)
        self.assertNotIn('wa-spunte lette', pagina)  # Verdi non l'ha ancora letto
        info = self.client.get(reverse('turni:info_messaggio', args=[m.pk]))
        self.assertContains(info, 'Non ancora letto · 1')
        # Verdi apre la chat: per Rossi le spunte diventano blu e Verdi è tra chi ha letto
        self.client.force_login(self.b.utente)
        self.assertContains(self.client.get(self.url), 'wa-tondo')
        self.assertEqual(self.client.get(reverse('turni:info_messaggio', args=[m.pk])).status_code, 403)  # solo chi l'ha scritto
        self.client.force_login(self.a.utente)
        self.assertIn('wa-spunte lette', self.client.get(self.url).content.decode())
        self.assertContains(self.client.get(reverse('turni:info_messaggio', args=[m.pk])), 'Letto da 1')

    def test_sondaggio_una_risposta(self):
        self.client.force_login(self.a.utente)
        self.client.post(reverse('turni:sondaggio_nuovo', args=[self.chat.pk]),
                         {'domanda': 'Quale sera?', 'opzione': ['Venerdì', 'Sabato', ''], 'una_risposta': '1'})
        so = Sondaggio.objects.get()
        self.assertEqual(so.opzioni.count(), 2)
        ven, sab = so.opzioni.all()
        self.client.force_login(self.b.utente)
        self.client.post(reverse('turni:vota_sondaggio', args=[so.pk]), {'opzione': ven.pk})
        self.client.post(reverse('turni:vota_sondaggio', args=[so.pk]), {'opzione': sab.pk})
        self.assertEqual(list(VotoSondaggio.objects.values_list('opzione_id', flat=True)), [sab.pk])  # una sola risposta
        self.assertContains(self.client.get(self.url), 'Quale sera?')

    def test_ufficio_ha_il_tondino_con_la_foto(self):
        uff = get_user_model().objects.create_user('ufficio', is_staff=True)
        self.client.force_login(uff)
        self.client.post(reverse('turni:foto_profilo'), {'foto': jpg()})
        self.assertTrue(uff.foto_profilo.foto)
        self.assertContains(self.client.get(reverse('turni:profilo')), reverse('turni:foto_utente_img', args=[uff.pk]))
