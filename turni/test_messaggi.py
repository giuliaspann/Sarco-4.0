import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from .models import Annuncio, Chat, Dipendente, IscrizionePush, MessaggioChat, RuoloApp, StatoMessaggi

URL = 'turni:messaggi'


class MessaggiTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.utenti = {}
        for nome, user in [('DRAME BOUBA', 'drame'), ("SPANO' A. MAURO", 'spano')]:
            u = User.objects.create_user(user, password='123456')
            Dipendente.objects.create(nome=nome, utente=u)
            self.utenti[user] = u
        self.resp = User.objects.create_user('resp', password='x')
        self.resp.user_permissions.add(Permission.objects.get(codename='approva_richieste'))
        for u in (*self.utenti.values(), self.resp):
            IscrizionePush.objects.create(utente=u, endpoint=f'https://push.example/{u.username}', p256dh='k', auth='a')
        self.chat = Chat.objects.get(nome='Turni')  # creata dalla migrazione 0012
        patcher = mock.patch('pywebpush.webpush')
        self.webpush = patcher.start()
        self.addCleanup(patcher.stop)

    def endpoint_avvisati(self):
        return sorted(c.args[0]['endpoint'].rsplit('/', 1)[1] for c in self.webpush.call_args_list)

    def test_bacheca_scrive_solo_ufficio_e_avvisa_tutti(self):
        self.client.login(username='drame', password='123456')
        self.client.post(reverse(URL), {'vista': 'bacheca', 'azione': 'annuncio', 'testo': 'ciao'})
        self.assertFalse(Annuncio.objects.exists())

        self.client.login(username='resp', password='x')
        self.client.post(reverse(URL), {'vista': 'bacheca', 'azione': 'annuncio', 'testo': 'Turni pubblicati', 'importante': '1'})
        self.assertTrue(Annuncio.objects.get().importante)
        self.assertEqual(self.endpoint_avvisati(), ['drame', 'spano'])

        # il pallino dei non letti si spegne aprendo la bacheca
        self.client.login(username='drame', password='123456')
        r = self.client.get(reverse('turni:miei_turni'))
        self.assertEqual(r.context['nav_messaggi'], 1)
        self.assertContains(self.client.get(reverse(URL), {'vista': 'bacheca'}), 'Turni pubblicati')
        self.assertEqual(self.client.get(reverse('turni:miei_turni')).context['nav_messaggi'], 0)

    def test_chat_notifiche_e_disattivazione(self):
        StatoMessaggi.objects.create(utente=self.utenti['spano'], notifiche_chat=False)
        self.client.login(username='drame', password='123456')
        self.client.post(reverse(URL), {'vista': 'chat', 'chat': self.chat.pk, 'azione': 'chat', 'testo': 'Io sono disponibile'})
        m = MessaggioChat.objects.get()
        self.assertEqual(self.endpoint_avvisati(), ['resp'])  # spano ha spento la chat, drame è l'autore
        dati = json.loads(self.webpush.call_args.args[1])
        self.assertEqual(dati['titolo'], 'Turni · Drame Bouba')

        # aggiornamento automatico: chi ha la chat aperta riceve i nuovi
        self.client.login(username='spano', password='123456')
        r = self.client.get(reverse('turni:chat_nuovi'), {'chat': self.chat.pk, 'dopo': 0})
        self.assertEqual([x['testo'] for x in r.json()['messaggi']], ['Io sono disponibile'])
        self.assertEqual(self.client.get(reverse('turni:chat_nuovi'), {'chat': self.chat.pk, 'dopo': m.pk}).json()['messaggi'], [])

    def test_eliminare_messaggi(self):
        m = MessaggioChat.objects.create(chat=self.chat, autore=self.utenti['drame'], testo='sbagliato')
        self.client.login(username='spano', password='123456')
        self.client.post(reverse(URL), {'vista': 'chat', 'chat': self.chat.pk, 'azione': 'elimina_chat', 'messaggio': m.pk})
        m.refresh_from_db()
        self.assertFalse(m.eliminato)
        self.client.login(username='resp', password='x')
        self.client.post(reverse(URL), {'vista': 'chat', 'chat': self.chat.pk, 'azione': 'elimina_chat', 'messaggio': m.pk})
        m.refresh_from_db()
        self.assertTrue(m.eliminato)
        self.assertNotContains(self.client.get(reverse(URL), {'vista': 'chat', 'chat': self.chat.pk}), 'sbagliato')

    def test_iscrizione_e_telefono_revocato(self):
        from pywebpush import WebPushException

        self.client.login(username='drame', password='123456')
        # un indirizzo che non è di un servizio di notifiche viene rifiutato (niente richieste verso server interni)
        for falso in ('https://push.example/nuovo', 'http://fcm.googleapis.com/x', 'https://169.254.169.254/latest'):
            r = self.client.post(
                reverse('turni:iscrivi_notifiche'),
                json.dumps({'endpoint': falso, 'keys': {'p256dh': 'p', 'auth': 'a'}}),
                content_type='application/json',
            )
            self.assertEqual(r.status_code, 400, falso)
        vero = 'https://fcm.googleapis.com/fcm/send/abc123'
        r = self.client.post(
            reverse('turni:iscrivi_notifiche'),
            json.dumps({'endpoint': vero, 'keys': {'p256dh': 'p', 'auth': 'a'}}),
            content_type='application/json',
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue(IscrizionePush.objects.filter(endpoint=vero).exists())

        risposta = mock.Mock(status_code=410)
        self.webpush.side_effect = WebPushException('revocata', response=risposta)
        from . import push

        push.invia([self.utenti['spano'].pk], 'x', 'y')
        self.assertFalse(IscrizionePush.objects.filter(utente=self.utenti['spano']).exists())


class GruppiChatTest(TestCase):
    def test_separatori_e_gruppi_come_whatsapp(self):
        from .views_messaggi import con_gruppi

        msg = [
            {'giorno': '2026-10-17', 'autore_id': 1},
            {'giorno': '2026-10-18', 'autore_id': 1},
            {'giorno': '2026-10-18', 'autore_id': 1},
            {'giorno': '2026-10-18', 'autore_id': 2},
        ]
        con_gruppi(msg)
        self.assertEqual([m['nuovo_giorno'] for m in msg], [True, True, False, False])
        self.assertEqual([m['primo'] for m in msg], [True, True, False, True])
