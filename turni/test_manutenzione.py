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
        self.assertEqual((i.chi_ha_segnalato, i.chi_ha_approvato, i.chi_ha_sistemato), ('Rossi Marco', 'Bianchi Luca', 'Torre Vito'))
        self.assertEqual(filtro.scorta, scorta + 1)
        self.assertEqual(sorted(p.nome for p in i.ricambi_usati.all()), ['Fascetta', 'Filtro olio motore'])
        self.assertEqual(self.avvisati(), ['marchese', 'operaio'])
        diario = list(i.eventi.values_list('testo', flat=True))
        self.assertEqual(diario[0], 'Guasto segnalato · macchina ferma')
        self.assertEqual(diario[-1], 'Riparato')

    def test_segnala_a_passi(self):
        self.entra('operaio')
        r = self.client.get(reverse('turni:segnala'))
        self.assertEqual([g for g, _, _, _ in r.context['gruppi']], ['macchinari', 'mezzi', 'segnaletica'])
        r = self.client.get(reverse('turni:segnala'), {'gruppo': 'mezzi'})
        self.assertEqual([nome for _, nome, _, _ in r.context['luoghi']], ['Mezzi interni', 'Mezzi esterni'])
        r = self.client.get(reverse('turni:segnala'), {'luogo': 'MEZZI'})
        self.assertIn(self.pala, r.context['elenco'])
        self.assertTrue(all(m.luogo == 'MEZZI' for m in r.context['elenco']))
        r = self.client.get(reverse('turni:segnala'), {'q': 'PALA1'})
        self.assertEqual([m.codice for m in r.context['elenco']], ['PZ-PALA1'])
        r = self.client.get(reverse('turni:segnala'), {'macchina': self.pala.pk})
        self.assertEqual(r.context['macchina'], self.pala)
        self.assertContains(r, 'name="foto"')

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
        for nome in ('manutenzione', 'interventi', 'macchine', 'ricambi', 'ordini', 'programmate', 'segnala'):
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

    def test_lavoro_fatto_senza_segnalazione(self):
        self.entra('operaio')
        self.assertEqual(self.client.get(reverse('turni:segnala'), {'lavoro': '1'}).status_code, 403)
        self.entra('vito')
        r = self.client.get(reverse('turni:segnala'), {'lavoro': '1', 'gruppo': 'macchinari'})
        self.assertContains(r, 'lavoro=1&amp;gruppo=macchinari&luogo=IMP1')
        vaglio = Macchina.objects.get(codice='IMP1-VAG')
        cinghia = Ricambio.objects.get(nome='Cinghia trapezoidale B68')
        scorta = cinghia.scorta
        self.client.post(reverse('turni:segnala'), {
            'lavoro': '1', 'macchina': vaglio.pk, 'descrizione': 'Sostituzione griglie vaglio', 'foto': [foto(), foto()],
            'pezzo_0': cinghia.pk, 'quantita_0': '1',
        })
        i = Intervento.objects.get(macchina=vaglio, tipo='LAVORO')
        cinghia.refresh_from_db()
        self.assertEqual((i.stato, i.chi_ha_sistemato, i.etichetta_stato, cinghia.scorta), ('COMPLETATA', 'Torre Vito', 'Fatto', scorta - 1))
        self.assertTrue(i.foto_riparazione)
        self.assertEqual(i.altre_foto.count(), 1)
        f = i.altre_foto.get()
        self.assertEqual(self.client.get(reverse('turni:foto_mn', args=['altra', f.pk])).status_code, 200)
        self.assertContains(self.client.get(reverse('turni:macchina', args=[vaglio.pk])), 'Sostituzione griglie vaglio')

    def test_lavoro_in_squadra_con_video_e_resta_da_fare(self):
        self.entra('vito')
        ciclone = Macchina.objects.get(codice='IMP2-PRE')
        video = SimpleUploadedFile('giro.mp4', b'0123456789' * 100, content_type='video/mp4')
        self.client.post(reverse('turni:segnala'), {
            'lavoro': '1', 'macchina': ciclone.pk, 'descrizione': 'Piastra supporto motore saldata', 'foto': foto(),
            'collaboratori': [self.altro.pk], 'video': video, 'resta': 'Ripristino dei vecchi tamburi',
        })
        i = Intervento.objects.get(macchina=ciclone, tipo='LAVORO')
        self.assertEqual(i.squadra, 'Torre Vito con Nizza Mirco')
        self.assertTrue(i.video)
        prossimo = Intervento.objects.get(macchina=ciclone, descrizione='Ripristino dei vecchi tamburi')
        self.assertEqual(prossimo.stato, 'SEGNALATA')
        # il video si scarica anche a pezzi (iPhone)
        r = self.client.get(reverse('turni:video_mn', args=['intervento', i.pk]), HTTP_RANGE='bytes=0-9')
        self.assertEqual((r.status_code, r.content, r['Content-Range']), (206, b'0123456789', 'bytes 0-9/1000'))

    def test_video_finto_rifiutato(self):
        self.entra('vito')
        n = Intervento.objects.count()
        finto = SimpleUploadedFile('virus.exe', b'MZ', content_type='application/octet-stream')
        self.client.post(reverse('turni:segnala'), {
            'lavoro': '1', 'macchina': self.pala.pk, 'descrizione': 'x', 'foto': foto(), 'video': finto,
        })
        self.assertEqual(Intervento.objects.count(), n)

    def test_pezzo_arrivato_dove_si_trova(self):
        self.entra('marchese')
        self.client.post(reverse('turni:nuovo_ordine'), {'descrizione': 'Specchietto Stralis', 'quantita': 1, 'foto': foto()})
        o = OrdineRicambio.objects.get()
        self.client.post(reverse('turni:ordini'), {'ordine': o.pk, 'azione': 'ordinato'})
        self.client.post(reverse('turni:ordini'), {'ordine': o.pk, 'azione': 'arrivato', 'dove': 'in ufficio'})
        o.refresh_from_db()
        self.assertEqual((o.stato, o.dove), ('ARRIVATO', 'in ufficio'))

    def test_pezzo_sistemato_e_bravo(self):
        self.entra('vito')
        lab = Macchina.objects.get(codice='LAB-VAG')
        self.client.post(reverse('turni:segnala'), {
            'lavoro': '1', 'macchina': lab.pk, 'tipo_lavoro': 'PEZZO', 'pezzo': 'Rete vaglio', 'foto': foto(),
        })
        i = Intervento.objects.get(macchina=lab)
        self.assertEqual((i.titolo_lavoro, i.descrizione), ('Pezzo sistemato · Rete vaglio', 'Pezzo sistemato · Rete vaglio'))
        self.assertContains(self.client.get(reverse('turni:home')), 'Manutenzione fatta')
        self.entra('marchese')
        self.webpush.reset_mock()
        for _ in range(2):  # un solo 👍 a testa
            self.client.post(reverse('turni:intervento', args=[i.pk]), {'azione': 'bravo'})
        self.assertEqual(i.eventi.filter(testo='👍').count(), 1)
        self.assertEqual(self.avvisati(), ['vito'])

    def test_togli_esempi(self):
        self.assertGreater(togli(), 0)
        self.assertFalse(Macchina.objects.exists())
        self.assertFalse(Ricambio.objects.exists())



@override_settings(MEDIA_ROOT=MEDIA)
class FermoImpiantoTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.operaio = User.objects.create_user('operaio', password='123456')
        Dipendente.objects.create(nome='ROSSI MARCO', utente=self.operaio)
        self.marchese = User.objects.create_user('marchese', password='123456')
        d = Dipendente.objects.get(nome='MARCHESE LEONARDO')
        d.utente = self.marchese
        d.save()
        IscrizionePush.objects.create(utente=self.marchese, endpoint='https://fcm.googleapis.com/fcm/send/marchese', p256dh='k', auth='a')
        patcher = mock.patch('pywebpush.webpush')
        self.webpush = patcher.start()
        self.addCleanup(patcher.stop)

    def test_fermo_e_ripartenza(self):
        from .models import FermoImpianto

        nastro = Macchina.objects.get(codice='IMP1-NAS1')
        self.client.login(username='operaio', password='123456')
        self.assertContains(self.client.get(reverse('turni:nuovo_fermo')), 'Impianto 1')
        r = self.client.get(reverse('turni:nuovo_fermo'), {'impianto': 'IMP1'})
        self.assertIn(nastro, r.context['macchine'])
        self.client.post(reverse('turni:nuovo_fermo'), {
            'impianto': 'IMP1', 'causa': 'NASTRO', 'macchina': nastro.pk, 'descrizione': 'strappato', 'foto': foto(),
        })
        f = FermoImpianto.objects.get()
        self.assertTrue(f.in_corso)
        self.assertEqual(f.chi_ha_segnalato, 'Rossi Marco')
        # la macchina diventa un intervento urgente con la stessa foto
        self.assertEqual((f.intervento.macchina, f.intervento.priorita, f.intervento.macchina_ferma), (nastro, 4, True))
        self.assertTrue(f.intervento.foto_guasto)
        self.assertEqual(self.webpush.call_count, 1)  # il responsabile manutenzione
        self.assertContains(self.client.get(reverse('turni:manutenzione')), 'Impianto 1 fermo da')

        # chi ha segnalato può segnare la ripartenza
        self.client.post(reverse('turni:fermo', args=[f.pk]), {'sistemazione': 'giuntato il nastro'})
        f.refresh_from_db()
        self.assertFalse(f.in_corso)
        self.assertEqual((f.sistemazione, f.chi_ha_fatto_ripartire), ('giuntato il nastro', 'Rossi Marco'))
        self.assertNotContains(self.client.get(reverse('turni:manutenzione')), 'fermo da')
        self.assertContains(self.client.get(reverse('turni:fermi')), 'Rottura nastro')

    def test_senza_causa_non_si_segnala_e_ora_non_nel_futuro(self):
        from .models import FermoImpianto

        self.client.login(username='operaio', password='123456')
        self.client.post(reverse('turni:nuovo_fermo'), {'impianto': 'SABBIA'})
        self.assertFalse(FermoImpianto.objects.exists())
        self.client.post(reverse('turni:nuovo_fermo'), {'impianto': 'SABBIA', 'causa': 'TRAMOGGIA', 'dal': '2099-01-01T10:00'})
        f = FermoImpianto.objects.get()
        self.assertLessEqual(f.fermo_dal, timezone.now())
        self.assertIsNone(f.intervento)


@override_settings(MEDIA_ROOT=MEDIA)
class ComunicazioniTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.u = {}
        for username, nome, mansione in (('operaio', 'ROSSI MARCO', 'OPERAIO'), ('palista', 'BIANCHI LUCA', 'PALISTA'),
                                         ('vito', 'TORRE VITO', 'MANUTENTORE')):
            self.u[username] = User.objects.create_user(username, password='123456')
            d, _ = Dipendente.objects.get_or_create(nome=nome)
            d.utente, d.mansione = self.u[username], mansione
            d.save()
        self.u['marchese'] = User.objects.create_user('marchese', password='123456')
        d = Dipendente.objects.get(nome='MARCHESE LEONARDO')
        d.utente = self.u['marchese']
        d.save()
        for u in self.u.values():
            IscrizionePush.objects.create(utente=u, endpoint=f'https://fcm.googleapis.com/fcm/send/{u.username}', p256dh='k', auth='a')
        patcher = mock.patch('pywebpush.webpush')
        self.webpush = patcher.start()
        self.addCleanup(patcher.stop)

    def avvisati(self):
        a = sorted({c.args[0]['endpoint'].rsplit('/', 1)[1] for c in self.webpush.call_args_list})
        self.webpush.reset_mock()
        return a

    def test_qualita_con_risposte_e_chiusura(self):
        from .models import Comunicazione

        self.client.login(username='operaio', password='123456')
        self.assertEqual(self.client.get(reverse('turni:nuova_comunicazione')).status_code, 403)
        self.client.login(username='marchese', password='123456')
        self.client.post(reverse('turni:nuova_comunicazione'), {
            'tipo': 'QUALITA', 'testo': 'Scarto barrotti al 14% nel 2T', 'luogo': 'IMP1', 'fascia': '2T',
            'destinatari': 'TUTTI', 'foto': [foto(), foto()],
        })
        c = Comunicazione.objects.get()
        self.assertEqual((c.foto.count(), c.chi_ha_scritto, c.stato), (2, 'Marchese Leonardo', 'APERTA'))
        self.assertEqual(self.avvisati(), ['operaio', 'palista', 'vito'])
        self.client.login(username='vito', password='123456')
        self.client.post(reverse('turni:comunicazione', args=[c.pk]), {'azione': 'gestione', 'testo': 'Già comunicato al capo turno'})
        c.refresh_from_db()
        self.assertEqual((c.stato, c.in_gestione_da), ('IN_GESTIONE', self.u['vito']))
        self.assertEqual(self.avvisati(), ['marchese'])
        # chi non se ne occupa non può chiuderla
        self.client.login(username='operaio', password='123456')
        self.client.post(reverse('turni:comunicazione', args=[c.pk]), {'azione': 'risolta'})
        c.refresh_from_db()
        self.assertEqual(c.stato, 'IN_GESTIONE')
        self.client.login(username='vito', password='123456')
        self.client.post(reverse('turni:comunicazione', args=[c.pk]), {'azione': 'risolta'})
        c.refresh_from_db()
        self.assertEqual(c.stato, 'RISOLTA')
        self.assertEqual(list(c.risposte.values_list('testo', flat=True)), ['Già comunicato al capo turno', 'Risolta'])

    def test_pala_non_disponibile_per_i_palisti(self):
        pala = Macchina.objects.get(codice='PZ-PALA1')
        adesso = timezone.localtime()
        self.client.login(username='marchese', password='123456')
        self.client.post(reverse('turni:nuova_comunicazione'), {
            'tipo': 'INDISPONIBILE', 'testo': 'Intervento Volvo sui freni', 'macchina': pala.pk, 'destinatari': 'PALISTI',
            'dal': (adesso - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M'), 'al': (adesso + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
        })
        self.assertEqual(self.avvisati(), ['palista'])  # il responsabile scrive, non riceve
        self.assertEqual(mn.stato_macchine([pala])[0].stato, 'ferma')
        self.client.login(username='palista', password='123456')
        self.assertContains(self.client.get(reverse('turni:home')), 'non disponibile')
        self.client.login(username='operaio', password='123456')
        self.assertNotContains(self.client.get(reverse('turni:home')), 'non disponibile')

    def test_fermo_programmato_di_un_turno(self):
        from .models import Comunicazione

        domani = timezone.localdate() + timedelta(days=1)
        self.client.login(username='marchese', password='123456')
        self.client.post(reverse('turni:nuova_comunicazione'), {
            'tipo': 'FERMO', 'luogo': 'IMP2', 'motivo': 'PULIZIA', 'giorno': domani.isoformat(), 'fascia': '2T', 'destinatari': 'TUTTI',
        })
        c = Comunicazione.objects.get()
        self.assertEqual((timezone.localtime(c.dal).hour, (c.al - c.dal).total_seconds() / 3600, c.testo), (14, 8, 'Pulizia'))
        self.assertIn('2° turno', c.periodo)
        self.assertEqual(self.avvisati(), ['operaio', 'palista', 'vito'])
        self.client.login(username='operaio', password='123456')
        self.assertContains(self.client.get(reverse('turni:home')), 'Impianto 2 fermo')
