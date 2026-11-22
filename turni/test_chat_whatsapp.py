"""Chat come WhatsApp (Giulia, 22/11/2026): video, risposta a un messaggio, reazioni, menu senza Ritardo/Bacheca."""

import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Chat, Dipendente, MessaggioChat, ReazioneChat
from .test_chat_nuova import jpg

MEDIA = tempfile.mkdtemp()


def video(nome='prova.mp4', tipo='video/mp4', dati=b'\x00' * 5000):
    return SimpleUploadedFile(nome, dati, content_type=tipo)


@override_settings(MEDIA_ROOT=MEDIA, PUSH_SINCRONO=True)
class ChatWhatsAppTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        U = get_user_model()
        self.chat = Chat.objects.create(nome='Prova WhatsApp', tutti=False)
        self.a = Dipendente.objects.create(nome='ROSSI MARIO', utente=U.objects.create_user('rossi', last_login=timezone.now()))
        self.b = Dipendente.objects.create(nome='VERDI ANNA', utente=U.objects.create_user('verdi', last_login=timezone.now()))
        self.chat.membri.add(self.a.utente, self.b.utente)
        self.url = reverse('turni:messaggi') + f'?vista=chat&chat={self.chat.pk}'

    def scrivi(self, **dati):
        return self.client.post(reverse('turni:messaggi'), {'vista': 'chat', 'chat': self.chat.pk, 'azione': 'chat', **dati})

    def test_video_dalla_galleria_e_registrato(self):
        self.client.force_login(self.a.utente)
        self.scrivi(testo='', foto=video())               # dalla galleria arriva nel campo delle foto
        self.scrivi(testo='nastro', video=video('rec.mov', 'video/quicktime'))  # «Registra un video»
        v1, v2 = MessaggioChat.objects.order_by('pk')
        self.assertTrue(v1.video and not v1.foto)
        self.assertEqual(v2.video_tipo, 'video/quicktime')
        r = self.client.get(reverse('turni:video_chat', args=[v1.pk]), HTTP_RANGE='bytes=0-99')
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r['Content-Range'], 'bytes 0-99/5000')
        pagina = self.client.get(self.url).content.decode()
        self.assertIn('class="wa-video"', pagina)
        self.assertIn('Registra un video', pagina)
        # nell'elenco delle chat: «🎥 Video» invece di una riga vuota
        self.client.force_login(self.b.utente)
        self.scrivi(testo='', foto=jpg())
        self.assertIn('📷 Foto', self.client.get(reverse('turni:messaggi')).content.decode())

    def test_video_troppo_grande(self):
        self.client.force_login(self.a.utente)
        from unittest import mock
        with mock.patch('turni.views_messaggi.MAX_VIDEO', 1000):
            self.scrivi(testo='', foto=video())
        self.assertFalse(MessaggioChat.objects.exists())

    def test_video_di_altra_chat_non_si_vede(self):
        altra = Chat.objects.create(nome='Riservata', tutti=False)
        m = MessaggioChat.objects.create(chat=altra, autore=self.b.utente, video=video())
        self.client.force_login(self.a.utente)
        self.assertEqual(self.client.get(reverse('turni:video_chat', args=[m.pk])).status_code, 404)

    def test_risposta_citata(self):
        orig = MessaggioChat.objects.create(chat=self.chat, autore=self.b.utente, testo='Pulizia nastro 3 alle 10')
        self.client.force_login(self.a.utente)
        self.scrivi(testo='Ok, ci penso io', risposta_a=orig.pk)
        m = MessaggioChat.objects.latest('pk')
        self.assertEqual(m.risposta_a, orig)
        pagina = self.client.get(self.url).content.decode()
        self.assertIn('class="wa-citazione', pagina)
        self.assertIn(f'data-vai="m{orig.pk}"', pagina)
        # la risposta a un messaggio di un'altra chat non si aggancia
        altra = Chat.objects.create(nome='Riservata', tutti=False)
        fuori = MessaggioChat.objects.create(chat=altra, autore=self.b.utente, testo='segreto')
        self.scrivi(testo='prova', risposta_a=fuori.pk)
        self.assertIsNone(MessaggioChat.objects.latest('pk').risposta_a)
        # nel JSON dell'aggiornamento automatico
        j = self.client.get(reverse('turni:chat_nuovi'), {'chat': self.chat.pk, 'dopo': orig.pk}).json()
        self.assertEqual(j['messaggi'][0]['risposta']['testo'], 'Pulizia nastro 3 alle 10')

    def test_reazioni(self):
        m = MessaggioChat.objects.create(chat=self.chat, autore=self.b.utente, testo='Fatto!')
        url = reverse('turni:reazione_chat', args=[m.pk])
        self.client.force_login(self.a.utente)
        r = self.client.post(url, {'emoji': '👍'}, HTTP_X_REQUESTED_WITH='fetch')
        self.assertEqual(r.json()['reazioni'][0], {'emoji': '👍', 'n': 1, 'mia': True, 'chi': 'Tu'})
        self.client.post(url, {'emoji': '❤️'}, HTTP_X_REQUESTED_WITH='fetch')   # cambia, non si somma
        self.assertEqual(list(ReazioneChat.objects.values_list('emoji', flat=True)), ['❤️'])
        self.client.post(url, {'emoji': '❤️'}, HTTP_X_REQUESTED_WITH='fetch')   # la stessa la toglie
        self.assertFalse(ReazioneChat.objects.exists())
        self.assertEqual(self.client.post(url, {'emoji': '💩'}).status_code, 400)
        # l'altra persona vede la reazione nell'aggiornamento automatico
        self.client.post(url, {'emoji': '😂'}, HTTP_X_REQUESTED_WITH='fetch')
        self.client.force_login(self.b.utente)
        j = self.client.get(reverse('turni:chat_nuovi'), {'chat': self.chat.pk, 'dopo': m.pk}).json()
        self.assertNotEqual(j['reazioni'][str(m.pk)][0]['chi'], 'Tu')
        self.assertFalse(j['reazioni'][str(m.pk)][0]['mia'])

    def test_reazione_in_chat_non_mia(self):
        altra = Chat.objects.create(nome='Riservata', tutti=False)
        m = MessaggioChat.objects.create(chat=altra, autore=self.b.utente, testo='segreto')
        self.client.force_login(self.a.utente)
        self.assertEqual(self.client.post(reverse('turni:reazione_chat', args=[m.pk]), {'emoji': '👍'}).status_code, 404)

    def test_menu_senza_ritardo_e_bacheca(self):
        self.client.force_login(self.a.utente)
        pagina = self.client.get(self.url).content.decode()
        menu = pagina.split('class="wa-menu-voci"')[1].split('</details>')[0]
        self.assertNotIn('Ritardo / uscita (privato)', menu)
        self.assertNotIn("Bacheca dell'ufficio", menu)
        self.assertIn('in-chat', pagina)   # dentro la chat il menu in basso sparisce
