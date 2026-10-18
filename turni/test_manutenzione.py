import shutil
import tempfile
from datetime import timedelta
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from . import manutenzione as mn
from .esempi_manutenzione import togli
from .models import (
    Dipendente, Fascia, Intervento, Settimana, IscrizionePush, Macchina, ManutenzioneProgrammata, OrdineRicambio, Ricambio, Turno,
)

MEDIA = tempfile.mkdtemp()


def foto():
    buf = BytesIO()
    Image.new('RGB', (40, 30), 'red').save(buf, 'JPEG')
    return SimpleUploadedFile('f.jpg', buf.getvalue(), content_type='image/jpeg')


@override_settings(MEDIA_ROOT=MEDIA)
class ManutenzioneTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        User = get_user_model()
        self.u = {}

        def persona(username, nome, **campi):
            utente = User.objects.create_user(username, password='123456')
            dip, _ = Dipendente.objects.get_or_create(nome=nome)
            dip.utente = utente
            for k, v in campi.items():
                setattr(dip, k, v)
            dip.save()
            self.u[username] = utente
            IscrizionePush.objects.create(utente=utente, endpoint=f'https://fcm.googleapis.com/fcm/send/{username}', p256dh='k', auth='a')
            return dip

        persona('operaio', 'ROSSI MARCO', mansione='OPERAIO')
        self.capo = persona('capo', 'BIANCHI LUCA', mansione='OPERAIO')
        self.vito = persona('vito', 'TORRE VITO', mansione='MANUTENTORE')
        self.altro = persona('nizza', 'NIZZA MIRCO', mansione='MANUTENTORE')
        persona('marchese', 'MARCHESE LEONARDO')  # responsabile manutenzione dalla migrazione
        persona('bonomo', 'BONOMO MICHELANGELO')  # acquisti dalla migrazione
        oggi = timezone.localdate()
        sett = Settimana.objects.create(lunedi=oggi - timedelta(days=oggi.weekday()))
        Turno.objects.create(settimana=sett, dipendente=self.capo, data=oggi, codice='1T', fascia=Fascia.MATTINA, capoturno=True)
        Turno.objects.create(settimana=sett, dipendente=self.vito, data=oggi, codice='1T', fascia=Fascia.MATTINA)
        self.pala = Macchina.objects.get(codice='PZ-PALA1')
        patcher = mock.patch('pywebpush.webpush')
        self.webpush = patcher.start()
        self.addCleanup(patcher.stop)

    def entra(self, username):
        self.client.login(username=username, password='123456')

    def avvisati(self):
        avvisati = sorted({c.args[0]['endpoint'].rsplit('/', 1)[1] for c in self.webpush.call_args_list})
        self.webpush.reset_mock()
        return avvisati

    def segnala(self, **extra):
        dati = {'macchina': self.pala.pk, 'descrizione': 'Perde olio', 'ferma': '1', 'foto': foto(), **extra}
        return self.client.post(reverse('turni:segnala'), dati)

    def test_flusso_completo_guasto(self):
        self.entra('operaio')
        r = self.segnala()
        i = Intervento.objects.get(segnalata_da=self.u['operaio'])
        self.assertRedirects(r, reverse('turni:intervento', args=[i.pk]))
        self.assertEqual((i.stato, i.priorita, i.macchina_ferma), ('SEGNALATA', 4, True))
        self.assertTrue(i.foto_guasto)
        self.assertEqual(self.avvisati(), ['capo', 'marchese'])  # capo turno di oggi e responsabile
        self.assertEqual(self.client.get(reverse('turni:foto_mn', args=['guasto', i.pk])).status_code, 200)

        # l'operaio non può approvare
        self.client.post(reverse('turni:intervento', args=[i.pk]), {'azione': 'approva', 'manutentore': self.vito.pk})
        i.refresh_from_db()
        self.assertEqual(i.stato, 'SEGNALATA')

        # il capo turno vede il manutentore di turno già proposto e approva
        self.entra('capo')
        r = self.client.get(reverse('turni:intervento', args=[i.pk]))
        self.assertEqual([d.pk for d in r.context['in_turno']], [self.vito.pk])
        self.client.post(reverse('turni:intervento', args=[i.pk]), {'azione': 'approva', 'manutentore': self.vito.pk})
        i.refresh_from_db()
        self.assertEqual((i.stato, i.assegnata_a, i.approvata_da), ('ASSEGNATA', self.vito, self.u['capo']))
        self.assertEqual(self.avvisati(), ['operaio', 'vito'])

        # un altro manutentore non può chiuderlo
        self.entra('nizza')
        self.client.post(reverse('turni:intervento', args=[i.pk]), {'azione': 'completa', 'lavoro': 'x', 'foto': foto()})
        i.refresh_from_db()
        self.assertEqual(i.stato, 'ASSEGNATA')

        # il manutentore assegnato: inizia, chiede un pezzo, poi chiude con foto e pezzi usati
        self.entra('vito')
        self.client.post(reverse('turni:intervento', args=[i.pk]), {'azione': 'inizia'})
        filtro = Ricambio.objects.get(nome='Filtro olio motore')
        self.client.post(reverse('turni:nuovo_ordine'), {'intervento': i.pk, 'ricambio': filtro.pk, 'quantita': 2, 'urgente': '1'})
        o = OrdineRicambio.objects.get(intervento=i)
        i.refresh_from_db()
        self.assertEqual((o.stato, i.stato), ('RICHIESTO', 'ATTESA_PEZZI'))
        self.assertEqual(self.avvisati(), ['marchese'])

        # senza foto non si chiude
        self.client.post(reverse('turni:intervento', args=[i.pk]), {'azione': 'completa', 'lavoro': 'Cambiato tubo'})
        i.refresh_from_db()
        self.assertEqual(i.stato, 'ATTESA_PEZZI')

        # ordine: approva il responsabile, ordinano gli acquisti, all'arrivo la scorta sale e l'intervento riparte
        self.entra('marchese')
        self.client.post(reverse('turni:ordini'), {'ordine': o.pk, 'azione': 'approva'})
        self.assertEqual(self.avvisati(), ['bonomo'])
        self.entra('operaio')
        self.client.post(reverse('turni:ordini'), {'ordine': o.pk, 'azione': 'ordinato'})
        o.refresh_from_db()
        self.assertEqual(o.stato, 'APPROVATO')
        self.entra('bonomo')
        self.client.post(reverse('turni:ordini'), {'ordine': o.pk, 'azione': 'ordinato', 'fornitore': 'Volvo CE'})
        scorta = filtro.scorta
        self.entra('vito')
        self.client.post(reverse('turni:ordini'), {'ordine': o.pk, 'azione': 'arrivato'})
        o.refresh_from_db(); i.refresh_from_db(); filtro.refresh_from_db()
        self.assertEqual((o.stato, o.fornitore, i.stato, filtro.scorta), ('ARRIVATO', 'Volvo CE', 'IN_CORSO', scorta + 2))

        self.client.post(reverse('turni:intervento', args=[i.pk]), {
            'azione': 'completa', 'lavoro': 'Cambiato filtro', 'ore': '1.5', 'foto': foto(),
            'pezzo_0': filtro.pk, 'quantita_0': '1', 'altro_1': 'Fascetta', 'quantita_1': '2',
        })
        i.refresh_from_db(); filtro.refresh_from_db()
        self.assertEqual((i.stato, float(i.ore_lavoro)), ('COMPLETATA', 1.5))
        self.assertTrue(i.foto_riparazione)
        self.assertEqual(filtro.scorta, scorta + 1)
        self.assertEqual(sorted(p.nome for p in i.ricambi_usati.all()), ['Fascetta', 'Filtro olio motore'])
        self.assertEqual(self.avvisati(), ['marchese', 'operaio'])
        diario = list(i.eventi.values_list('testo', flat=True))
        self.assertEqual(diario[0], 'Guasto segnalato · macchina ferma')
        self.assertEqual(diario[-1], 'Riparato')

    def test_segnala_in_tre_passi(self):
        self.entra('operaio')
        r = self.client.get(reverse('turni:segnala'))
        self.assertIn('Mezzi interni', [nome for _, nome, _, _ in r.context['luoghi']])
        r = self.client.get(reverse('turni:segnala'), {'luogo': 'MEZZI'})
        self.assertIn(self.pala, r.context['elenco'])
        self.assertTrue(all(m.luogo == 'MEZZI' for m in r.context['elenco']))
        r = self.client.get(reverse('turni:segnala'), {'q': 'PALA1'})
        self.assertEqual([m.codice for m in r.context['elenco']], ['PZ-PALA1'])
        r = self.client.get(reverse('turni:segnala'), {'macchina': self.pala.pk})
        self.assertEqual(r.context['macchina'], self.pala)
        self.assertContains(r, 'Foto del guasto')

    def test_segnalazione_senza_foto_rifiutata(self):
        self.entra('operaio')
        n = Intervento.objects.count()
        self.client.post(reverse('turni:segnala'), {'macchina': self.pala.pk, 'descrizione': 'rotto'})
        self.assertEqual(Intervento.objects.count(), n)

    def test_rifiuto_avvisa_chi_ha_segnalato(self):
        self.entra('operaio')
        self.segnala(ferma='0')
        i = Intervento.objects.get(segnalata_da=self.u['operaio'])
        self.assertEqual(i.priorita, 2)
        self.avvisati()
        self.entra('marchese')
        self.client.post(reverse('turni:intervento', args=[i.pk]), {'azione': 'rifiuta', 'motivo': 'già sistemato'})
        i.refresh_from_db()
        self.assertEqual((i.stato, i.motivo_rifiuto), ('RIFIUTATA', 'già sistemato'))
        self.assertEqual(self.avvisati(), ['operaio'])

    def test_pezzo_senza_intervento_vuole_la_foto_e_dal_responsabile_e_gia_approvato(self):
        self.entra('operaio')
        self.assertEqual(self.client.get(reverse('turni:nuovo_ordine')).status_code, 403)
        self.entra('vito')
        self.client.post(reverse('turni:nuovo_ordine'), {'descrizione': 'Tubo 1/2', 'quantita': 1})
        self.assertFalse(OrdineRicambio.objects.exists())
        self.entra('marchese')
        self.client.post(reverse('turni:nuovo_ordine'), {'descrizione': 'Tubo 1/2', 'quantita': 1, 'foto': foto()})
        self.assertEqual(OrdineRicambio.objects.get().stato, 'APPROVATO')

    def test_programmate_diventano_interventi_una_volta_sola(self):
        p = ManutenzioneProgrammata.objects.create(macchina=self.pala, attivita='Controllo freni', ogni_giorni=10,
                                                   ultima=timezone.localdate() - timedelta(days=10), istruzioni='Pastiglie\nLiquido')
        nuovi = [i for i in mn.genera_programmate() if i.piano == p]
        self.assertEqual(len(nuovi), 1)
        self.assertIn('• Pastiglie', nuovi[0].descrizione)
        self.assertFalse([i for i in mn.genera_programmate() if i.piano == p])
        i = nuovi[0]
        self.entra('marchese')
        self.client.post(reverse('turni:intervento', args=[i.pk]), {'azione': 'approva', 'manutentore': self.vito.pk})
        self.entra('vito')
        self.client.post(reverse('turni:intervento', args=[i.pk]), {'azione': 'completa', 'lavoro': 'Fatto', 'foto': foto()})
        p.refresh_from_db()
        self.assertEqual(p.ultima, timezone.localdate())
        self.assertEqual(p.prossima, timezone.localdate() + timedelta(days=10))

    def test_pagine_e_permessi(self):
        self.entra('operaio')
        for nome in ('manutenzione', 'macchine', 'ricambi', 'ordini', 'programmate', 'segnala'):
            self.assertEqual(self.client.get(reverse(f'turni:{nome}')).status_code, 200, nome)
        self.assertEqual(self.client.get(reverse('turni:macchina', args=[self.pala.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('turni:etichette')).status_code, 403)
        # l'operaio non tocca il magazzino né le macchine
        r = Ricambio.objects.first()
        self.client.post(reverse('turni:ricambi'), {'azione': 'scorta', 'ricambio': r.pk, 'verso': 'piu'})
        self.assertEqual(Ricambio.objects.get(pk=r.pk).scorta, r.scorta)
        self.client.post(reverse('turni:macchine'), {'azione': 'togli_esempi'})
        self.assertTrue(Macchina.objects.filter(esempio=True).exists())

        self.entra('marchese')
        r = self.client.get(reverse('turni:etichette'))
        self.assertContains(r, 'data:image/svg+xml')
        self.assertContains(self.client.get(reverse('turni:home')), 'Manutenzione')

    def test_pallino_della_barra(self):
        self.entra('capo')
        prima = self.client.get(reverse('turni:home')).context['nav_manutenzione']
        self.entra('operaio')
        self.segnala()
        self.entra('capo')
        self.assertEqual(self.client.get(reverse('turni:home')).context['nav_manutenzione'], prima + 1)

    def test_togli_esempi(self):
        self.assertGreater(togli(), 0)
        self.assertFalse(Macchina.objects.exists())
        self.assertFalse(Ricambio.objects.exists())

