from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from . import accessi
from .models import Chat, Dipendente, MessaggioChat, RuoloApp
from .organigramma import CHAT, PROFILI
from .richieste import e_responsabile

URL = 'turni:messaggi'


class ChatAziendaliTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.operaio = User.objects.create_user('drame', password='123456')
        Dipendente.objects.create(nome='DRAME BOUBA', utente=self.operaio)
        self.titolare = User.objects.create_user('spano.antonio', password='123456')
        d = Dipendente.objects.get(nome='SPANÒ ANTONIO UGO')  # dalla migrazione 0012
        d.utente = self.titolare
        d.save()
        patcher = mock.patch('pywebpush.webpush')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_profili_e_chat_dalla_migrazione(self):
        self.assertEqual(list(Chat.objects.values_list('nome', flat=True)), [n for n, _ in CHAT])
        for nome, _, ruolo in PROFILI:
            self.assertEqual(Dipendente.objects.get(nome=nome).ruolo_app, ruolo)

    def test_dashboard_mostra_tutte_le_chat(self):
        self.client.login(username='drame', password='123456')
        r = self.client.get(reverse(URL))
        for nome, _ in CHAT:
            self.assertContains(r, nome)
        self.assertContains(r, 'Bacheca')

    def test_non_letti_per_chat(self):
        pulizia, turni = Chat.objects.get(nome='Pulizia'), Chat.objects.get(nome='Turni')
        MessaggioChat.objects.create(chat=pulizia, autore=self.titolare, testo='Piazzale pulito?')
        MessaggioChat.objects.create(chat=turni, autore=self.titolare, testo='Domenica serve uno')
        self.client.login(username='drame', password='123456')
        r = self.client.get(reverse(URL))
        self.assertEqual([c['nuovi'] for c in r.context['elenco'] if c['nuovi']], [1, 1])
        self.client.get(reverse(URL), {'vista': 'chat', 'chat': pulizia.pk})
        self.assertEqual(self.client.get(reverse('turni:home')).context['nav_messaggi'], 1)

    def test_chat_riservata_e_storico_per_la_direzione(self):
        riservata = Chat.objects.create(nome='Capi turno', tutti=False)
        m = MessaggioChat.objects.create(chat=riservata, autore=self.titolare, testo='solo per i capi', eliminato=True)
        self.client.login(username='drame', password='123456')
        self.assertRedirects(self.client.get(reverse(URL), {'vista': 'chat', 'chat': riservata.pk}), reverse(URL))
        self.assertEqual(self.client.get(reverse('turni:chat_nuovi'), {'chat': riservata.pk}).status_code, 404)
        self.client.post(reverse(URL), {'vista': 'chat', 'chat': riservata.pk, 'azione': 'chat', 'testo': 'intruso'})
        self.assertEqual(riservata.messaggi.count(), 1)

        # la direzione è sempre dentro e legge anche i messaggi eliminati
        self.client.login(username='spano.antonio', password='123456')
        r = self.client.get(reverse(URL), {'vista': 'chat', 'chat': riservata.pk})
        self.assertContains(r, 'solo per i capi')
        self.assertContains(r, 'eliminato')
        self.assertTrue(m.eliminato)

    def test_operaio_non_legge_i_messaggi_eliminati(self):
        turni = Chat.objects.get(nome='Turni')
        MessaggioChat.objects.create(chat=turni, autore=self.titolare, testo='testo cancellato', eliminato=True)
        self.client.login(username='drame', password='123456')
        r = self.client.get(reverse(URL), {'vista': 'chat', 'chat': turni.pk})
        self.assertNotContains(r, 'testo cancellato')
        self.assertContains(r, 'Messaggio eliminato')

    def test_responsabile_turni_ha_le_pagine_ufficio(self):
        ancona = Dipendente.objects.get(nome='ANCONA MARIO')
        self.assertEqual(ancona.ruolo_app, RuoloApp.RESP_TURNI)
        username, pin = accessi.crea_credenziali(ancona)
        utente = get_user_model().objects.get(username=username)
        self.assertTrue(utente.is_staff)
        self.assertTrue(e_responsabile(utente))
        # la direzione invece no: entra nelle chat ma non approva i turni
        username, _ = accessi.crea_credenziali(Dipendente.objects.get(nome='MARCHESE LEONARDO'))
        self.assertFalse(e_responsabile(get_user_model().objects.get(username=username)))
