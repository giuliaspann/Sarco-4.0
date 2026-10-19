import os
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from . import assistente
from .models import AvvisoAssenza, ConversazioneAssistente, ModificaTurno, Turno
from . import test_richieste
from .tests import LUNEDI


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


class AssistenteAppTest(TestCase):
    """Le altre funzioni dell'app passate dall'assistente: sempre con conferma, stesse regole."""

    MAR = test_richieste.RichiesteTest.MAR

    def setUp(self):
        test_richieste.RichiesteTest.setUp(self)
        p = mock.patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-ant-prova-0123456789abcdefghij'})
        p.start()
        self.addCleanup(p.stop)
        w = mock.patch('pywebpush.webpush')
        w.start()
        self.addCleanup(w.stop)
        self.u = self.spano.utente

    def test_fermo_e_ripartenza(self):
        from . import assistente_app as app
        from .models import FermoImpianto

        dati = {'impianto': 'IMP1', 'causa': 'NASTRO', 'macchina_id': 0, 'descrizione': 'nastro rotto',
                'giorno': LUNEDI.isoformat(), 'dalle': '07:00', 'ripartito_alle': ''}
        self.assertIn('Fermo Impianto 1', app.prepara('proponi_fermo', dati, self.u))
        self.assertFalse(FermoImpianto.objects.exists())
        app.esegui('proponi_fermo', dati, self.u)
        f = FermoImpianto.objects.get()
        self.assertIn(f'id={f.pk}', app.leggi('fermi_in_corso', {}, self.u))
        app.esegui('proponi_ripartenza', {'fermo_id': f.pk, 'alle': '', 'sistemazione': 'nastro cambiato'}, self.u)
        f.refresh_from_db()
        self.assertIsNotNone(f.ripartito_il)

    def test_guasto_vuole_la_foto(self):
        from . import assistente_app as app
        from .models import Macchina

        m = Macchina.objects.filter(attiva=True).first() or Macchina.objects.create(codice='T1', nome='Vaglio', luogo='IMP1')
        with self.assertRaises(app.Errore):
            app.prepara('proponi_guasto', {'macchina_id': m.pk, 'descrizione': 'fa rumore', 'macchina_ferma': False}, self.u)

    def test_produzione_e_analisi(self):
        from . import assistente_app as app
        from .models import AnalisiProdotto, ProduzioneTurno

        app.esegui('proponi_produzione', {'giorno': LUNEDI.isoformat(), 'fascia': '1T',
                                          'righe': [{'codice': 'a', 'tonnellate': 40.5}, {'codice': 'E-', 'tonnellate': 2}]}, self.u)
        self.assertEqual(ProduzioneTurno.objects.get().righe.count(), 2)
        with self.assertRaises(app.Errore):
            app.prepara('proponi_produzione', {'giorno': LUNEDI.isoformat(), 'fascia': '1T', 'righe': [{'codice': 'ZZ', 'tonnellate': 1}]}, self.u)
        testo = app.prepara('proponi_analisi', {'giorno': LUNEDI.isoformat(), 'fascia': '', 'campione': 'BIANCO', 'peso_kg': 20,
                                                'numero': 57, 'csp': 0.8, 'vetro_ceramico': None, 'metallo': None,
                                                'organico': None, 'plastica': None, 'cristallo': None}, self.u)
        self.assertIn('FUORI LIMITE: CSP', testo)
        self.assertFalse(AnalisiProdotto.objects.exists())

    def test_foto_in_chat_va_con_la_proposta(self):
        from .models import ConversazioneAssistente
        from .test_statistiche import jpeg_finto
        from django.core.files.uploadedfile import SimpleUploadedFile

        risposte = [
            risposta('tool_use', blocco('tool_use', id='t1', name='proponi_produzione', input={
                'giorno': LUNEDI.isoformat(), 'fascia': '2T', 'righe': [{'codice': 'A', 'tonnellate': 41}], 'note': ''})),
            risposta('end_turn', blocco('text', text='Premi Conferma.')),
        ]
        finto = mock.MagicMock()
        finto.return_value.beta.messages.create.side_effect = risposte
        self.client.login(username='spano', password='123456')
        with self.settings(MEDIA_ROOT=__import__('tempfile').mkdtemp()), mock.patch('anthropic.Anthropic', finto):
            j = self.client.post(reverse('turni:assistente'), {'testo': 'ecco il display', 'foto': SimpleUploadedFile('d.jpg', jpeg_finto(), 'image/jpeg')}).json()
            self.assertIn('con foto', j['proposte'][0]['riassunto'])
            primo = finto.return_value.beta.messages.create.call_args_list[0].kwargs['messages'][0]['content']
            self.assertEqual(primo[0]['type'], 'image')
            self.client.post(reverse('turni:assistente_conferma'), {'id': j['proposte'][0]['id'], 'accetta': True}, content_type='application/json')
            from .models import ProduzioneTurno
            self.assertTrue(ProduzioneTurno.objects.get().foto)
        self.assertTrue(ConversazioneAssistente.objects.get().foto)
