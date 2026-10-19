import os
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from . import assistente
from .models import AvvisoAssenza, ConversazioneAssistente, ModificaTurno, Turno
from . import test_richieste


def blocco(tipo, **campi):
    return SimpleNamespace(type=tipo, to_dict=lambda: {'type': tipo, **campi}, **campi)


def risposta(stop, *blocchi):
    return SimpleNamespace(stop_reason=stop, content=list(blocchi))


class AssistenteTest(TestCase):
    MAR, MER = test_richieste.RichiesteTest.MAR, test_richieste.RichiesteTest.MER

    def setUp(self):
        test_richieste.RichiesteTest.setUp(self)
        p = mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-prova-0123456789abcdefghij'})
        p.start()
        self.addCleanup(p.stop)
        self.client.login(username='spano', password='123456')

    def test_spento_senza_chiave(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}):
            self.assertNotContains(self.client.get(reverse('turni:miei_turni')), 'id="as-apri"')
            self.assertEqual(self.client.get(reverse('turni:assistente')).status_code, 404)

    def test_fumetto_e_suggerimenti(self):
        self.assertContains(self.client.get(reverse('turni:miei_turni')), 'id="as-apri"')
        j = self.client.get(reverse('turni:assistente')).json()
        self.assertIn('Che turno faccio sabato?', j['suggerimenti'])
        self.assertNotIn('Quali richieste devo approvare?', j['suggerimenti'])

    def test_propone_e_poi_conferma(self):
        risposte = [
            risposta('tool_use', blocco('tool_use', id='t1', name='proponi_avviso', input={
                'tipo': 'RITARDO', 'giorno': self.MAR.isoformat(), 'dalle': '', 'alle': '09:30', 'nota': ''})),
            risposta('end_turn', blocco('text', text='Ho preparato l\'avviso: premi Conferma.')),
        ]
        finto = mock.MagicMock()
        finto.return_value.beta.messages.create.side_effect = risposte
        with mock.patch('anthropic.Anthropic', finto):
            j = self.client.post(reverse('turni:assistente'), {'testo': 'domani entro alle 9 e mezza'}, content_type='application/json').json()
        self.assertIn('Conferma', j['risposta'])
        self.assertEqual(len(j['proposte']), 1)
        self.assertIn('entra alle 9:30', j['proposte'][0]['riassunto'])
        self.assertFalse(AvvisoAssenza.objects.exists())  # niente parte senza conferma
        j = self.client.post(reverse('turni:assistente_conferma'), {'id': j['proposte'][0]['id'], 'accetta': True},
                             content_type='application/json').json()
        a = AvvisoAssenza.objects.get()
        self.assertEqual((a.tipo, a.orario), ('RITARDO', 'entra alle 9:30'))
        # la stessa proposta non si può confermare due volte
        self.assertEqual(self.client.post(reverse('turni:assistente_conferma'), {'id': 'x', 'accetta': True},
                                          content_type='application/json').status_code, 400)
        storia = ConversazioneAssistente.objects.get().per_lo_schermo()
        self.assertEqual([m['chi'] for m in storia], ['io', 'bot', 'esito'])

    def test_leggere_turni(self):
        testo = assistente.leggi('turni_di', {'nome': 'io', 'dal': self.MAR.isoformat(), 'al': self.MER.isoformat()}, self.spano.utente)
        self.assertIn('Capo turno', testo)
        self.assertIn('Riposo', testo)
        with self.assertRaises(assistente.Errore):
            assistente.trova_persona('Nessuno Inesistente', self.spano.utente)

    def test_permessi_per_ruolo(self):
        nomi = lambda u: {t['name'] for t in assistente.strumenti(u)}
        self.assertNotIn('proponi_modifica_turno', nomi(self.spano.utente))
        self.assertIn('proponi_decisione', nomi(self.resp))
        with self.assertRaises(assistente.Errore):
            assistente.esegui('proponi_modifica_turno', {'nome': 'Drame', 'giorno': self.MER.isoformat(), 'fascia': '1T',
                                                         'postazione': 'IMP1', 'capoturno': False}, self.spano.utente)

    def test_ufficio_modifica_settimana_caricata(self):
        uff = get_user_model().objects.create_user('uff', password='x', is_staff=True)
        dati = {'nome': 'Drame', 'giorno': self.MER.isoformat(), 'fascia': '1T', 'postazione': 'IMP1', 'capoturno': False}
        self.assertIn('Riposo', assistente.prepara('proponi_modifica_turno', dati, uff))
        assistente.esegui('proponi_modifica_turno', dati, uff)
        t = Turno.objects.get(dipendente=self.drame, data=self.MER)
        self.assertEqual((t.fascia, t.postazione), ('1T', 'IMP1'))
        self.assertEqual(ModificaTurno.objects.get().dipendente, self.drame)  # presa visione richiesta

    def test_chiave_scritta_male(self):
        with mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-curl https://api.anthropic.com --header x'}):
            finto = mock.MagicMock()
            with mock.patch('anthropic.Anthropic', finto):
                r = self.client.post(reverse('turni:assistente'), {'testo': 'ciao'}, content_type='application/json')
            self.assertEqual(r.status_code, 502)
            self.assertIn('non è scritta bene', r.json()['errore'])
            finto.assert_not_called()
