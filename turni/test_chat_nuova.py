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
        info = self.client.get(reverse('turni:info_messaggio', args=[m.pk]))
        self.assertContains(info, 'Letto da 1')
        self.assertContains(info, 'oggi alle')  # l'orario in cui l'ha visto

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
        self.assertContains(self.client.get(reverse('turni:home')), 'hu-foto')  # anche in home


@override_settings(PUSH_SINCRONO=True)
class MembriChatTest(TestCase):
    def test_lista_partecipanti_dal_titolo(self):
        U = get_user_model()
        chat = Chat.objects.create(nome='Laboratorio', tutti=False)
        a = Dipendente.objects.create(nome='ROSSI MARIO', utente=U.objects.create_user('rossi'), qualifica='Analista')
        b = Dipendente.objects.create(nome='VERDI ANNA', utente=U.objects.create_user('verdi'))
        fuori = Dipendente.objects.create(nome='NERI LUCA', utente=U.objects.create_user('neri'))
        chat.membri.add(a.utente, b.utente)
        self.client.force_login(a.utente)
        url = reverse('turni:membri_chat', args=[chat.pk])
        self.assertContains(self.client.get(reverse('turni:messaggi') + f'?vista=chat&chat={chat.pk}'), url)
        r = self.client.get(url)
        for t in ('Gruppo · 2 membri', '>Tu<', 'Analista', 'Verdi Anna'):
            self.assertContains(r, t)
        self.client.force_login(fuori.utente)
        self.assertEqual(self.client.get(url).status_code, 404)


@override_settings(PUSH_SINCRONO=True)
class GruppiChatTest(TestCase):
    def setUp(self):
        U = get_user_model()
        self.chat = Chat.objects.create(nome='Laboratorio', tutti=False)
        self.uff = U.objects.create_user('uff', is_staff=True)
        self.a = Dipendente.objects.create(nome='ROSSI MARIO', utente=U.objects.create_user('rossi'))
        self.b = Dipendente.objects.create(nome='VERDI ANNA', utente=U.objects.create_user('verdi'))
        self.chat.membri.add(self.a.utente, self.uff)
        MessaggioChat.objects.create(chat=self.chat, autore=self.a.utente, testo='Campione pronto, vedi www.sarco.it')
        MessaggioChat.objects.create(chat=self.chat, autore=self.a.utente, testo='Vecchio campione', eliminato=True)

    def test_menu_cerca_e_media(self):
        self.client.force_login(self.a.utente)
        pagina = self.client.get(reverse('turni:messaggi') + f'?vista=chat&chat={self.chat.pk}')
        for nome in ('membri_chat', 'cerca_chat', 'media_chat'):
            self.assertContains(pagina, reverse(f'turni:{nome}', args=[self.chat.pk]))
        self.assertNotContains(pagina, 'Aggiungi membri')  # solo ufficio, responsabili e direzione
        r = self.client.get(reverse('turni:cerca_chat', args=[self.chat.pk]), {'q': 'campione'})
        self.assertContains(r, '1 messaggio')
        self.assertNotContains(r, 'Vecchio campione')
        r = self.client.get(reverse('turni:media_chat', args=[self.chat.pk]), {'quale': 'link'})
        self.assertContains(r, 'href="https://www.sarco.it')
        self.assertEqual(self.client.get(reverse('turni:aggiungi_membri', args=[self.chat.pk])).status_code, 403)

    def test_ufficio_aggiunge_un_membro(self):
        self.client.force_login(self.uff)
        url = reverse('turni:aggiungi_membri', args=[self.chat.pk])
        self.assertContains(self.client.get(url), 'Verdi Anna')
        self.client.post(url, {'utenti': [self.b.utente.pk]})
        self.assertTrue(self.chat.membri.filter(pk=self.b.utente.pk).exists())
        self.client.force_login(self.b.utente)
        self.assertEqual(self.client.get(reverse('turni:membri_chat', args=[self.chat.pk])).status_code, 200)


@override_settings(MEDIA_ROOT=MEDIA, PUSH_SINCRONO=True)
class DocumentiENotificheGruppoTest(TestCase):
    def setUp(self):
        U = get_user_model()
        self.chat = Chat.objects.create(nome='Laboratorio', tutti=False)
        self.a = Dipendente.objects.create(nome='ROSSI MARIO', utente=U.objects.create_user('rossi'))
        self.b = Dipendente.objects.create(nome='VERDI ANNA', utente=U.objects.create_user('verdi'))
        self.chat.membri.add(self.a.utente, self.b.utente)

    def scrivi(self, **dati):
        return self.client.post(reverse('turni:messaggi'), {'vista': 'chat', 'chat': self.chat.pk, 'azione': 'chat', **dati})

    def test_documento_inviato_si_scarica_e_sta_in_media(self):
        self.client.force_login(self.a.utente)
        self.scrivi(testo='', documento=SimpleUploadedFile('Procedura campioni.pdf', b'%PDF-1.4 prova', content_type='application/pdf'))
        m = MessaggioChat.objects.get()
        self.assertEqual(m.documento_nome, 'Procedura campioni.pdf')
        self.client.force_login(self.b.utente)
        pagina = self.client.get(reverse('turni:messaggi') + f'?vista=chat&chat={self.chat.pk}')
        self.assertContains(pagina, 'Procedura campioni.pdf')
        r = self.client.get(reverse('turni:documento_chat', args=[m.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(b''.join(r.streaming_content), b'%PDF-1.4 prova')
        self.assertContains(self.client.get(reverse('turni:media_chat', args=[self.chat.pk]), {'quale': 'documenti'}), 'Procedura campioni.pdf')
        # un file non ammesso viene rifiutato
        self.scrivi(testo='', documento=SimpleUploadedFile('virus.exe', b'MZ', content_type='application/octet-stream'))
        self.assertEqual(MessaggioChat.objects.count(), 1)

    def test_notifiche_spente_solo_per_questo_gruppo(self):
        from .views_messaggi import destinatari
        self.client.force_login(self.b.utente)
        self.assertContains(self.client.get(reverse('turni:membri_chat', args=[self.chat.pk])), 'Attive')
        self.client.post(reverse('turni:notifiche_gruppo', args=[self.chat.pk]))
        self.assertContains(self.client.get(reverse('turni:membri_chat', args=[self.chat.pk])), 'Disattivate')
        self.assertNotIn(self.b.utente.pk, list(destinatari(self.a.utente, self.chat)))
        altra = Chat.objects.create(nome='Altra prova', tutti=True)
        self.assertIn(self.b.utente.pk, list(destinatari(self.a.utente, altra)))
