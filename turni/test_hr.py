"""Home dell'ufficio, Scadenze e Documenti con presa visione (Giulia, 11/11/2026)."""

import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Dipendente, Documento, PresaVisione, Scadenza

MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=MEDIA, PUSH_SINCRONO=True)
class HrTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        U = get_user_model()
        self.uff = U.objects.create_user('uff', is_staff=True)
        self.rossi = Dipendente.objects.create(nome='ROSSI MARIO', utente=U.objects.create_user('rossi'))
        self.verdi = Dipendente.objects.create(nome='VERDI ANNA', utente=U.objects.create_user('verdi'))
        self.oggi = timezone.localdate()

    def pdf(self, nome='doc.pdf'):
        return SimpleUploadedFile(nome, b'%PDF-1.4 prova', content_type='application/pdf')

    def test_home_ufficio_ha_le_sezioni_e_il_tasto_indietro_nelle_pagine(self):
        self.client.force_login(self.uff)
        r = self.client.get(reverse('turni:home'))
        for t in ('Ogni giorno', 'Persone', 'Azienda', reverse('turni:scadenze'), reverse('turni:documenti_ufficio'),
                  reverse('turni:archivio'), reverse('turni:accessi'), reverse('turni:anagrafica'),
                  reverse('turni:ufficio_turni'), reverse('turni:calendario')):
            self.assertContains(r, t)
        for nome in ('scadenze', 'documenti_ufficio', 'accessi', 'anagrafica', 'ufficio_turni', 'importa', 'calendario'):
            self.assertContains(self.client.get(reverse(f'turni:{nome}')), 'tasto-indietro', msg_prefix=nome)

    def test_scadenze_avviso_rinnovo_e_chiusura(self):
        self.client.force_login(self.uff)
        self.client.post(reverse('turni:scadenze'), {'azione': 'aggiungi', 'dipendente': self.rossi.pk, 'tipo': 'VISITA',
                                                     'scade_il': (self.oggi + timedelta(days=10)).isoformat(), 'preavviso': '30'})
        s = Scadenza.objects.get()
        self.assertEqual(s.stato, 'vicina')
        self.assertContains(self.client.get(reverse('turni:notifiche')), 'Visita medica · Rossi')
        self.client.post(reverse('turni:scadenze'), {'azione': 'rinnova', 'scadenza': s.pk,
                                                     'nuova': (self.oggi + timedelta(days=365)).isoformat()})
        s.refresh_from_db()
        self.assertEqual(s.stato, 'ok')
        self.assertNotContains(self.client.get(reverse('turni:notifiche')), 'Visita medica · Rossi')
        self.client.post(reverse('turni:scadenze'), {'azione': 'chiudi', 'scadenza': s.pk})
        s.refresh_from_db()
        self.assertIsNotNone(s.chiusa_il)

    def test_scadenze_solo_ufficio(self):
        self.client.force_login(self.rossi.utente)
        self.assertEqual(self.client.get(reverse('turni:scadenze')).status_code, 403)
        self.assertEqual(self.client.get(reverse('turni:documenti_ufficio')).status_code, 403)

    def test_busta_paga_la_vede_solo_il_suo_dipendente(self):
        self.client.force_login(self.uff)
        self.client.post(reverse('turni:documenti_ufficio'), {'titolo': 'Busta ottobre', 'tipo': 'BUSTA', 'a_chi': self.rossi.pk,
                                                              'file': self.pdf()})
        d = Documento.objects.get()
        self.client.force_login(self.rossi.utente)
        self.assertContains(self.client.get(reverse('turni:documenti')), 'Busta ottobre')
        self.assertEqual(self.client.get(reverse('turni:documento_file', args=[d.pk])).status_code, 200)
        self.client.force_login(self.verdi.utente)
        self.assertNotContains(self.client.get(reverse('turni:documenti')), 'Busta ottobre')
        self.assertEqual(self.client.get(reverse('turni:documento_file', args=[d.pk])).status_code, 403)

    def test_presa_visione_dagli_avvisi(self):
        self.client.force_login(self.uff)
        self.client.post(reverse('turni:documenti_ufficio'), {'titolo': 'Regolamento DPI', 'tipo': 'REGOLAMENTO', 'a_chi': 'tutti',
                                                              'presa_visione': '1', 'file': self.pdf()})
        d = Documento.objects.get()
        self.client.force_login(self.verdi.utente)
        self.assertContains(self.client.get(reverse('turni:miei_turni')), 'Regolamento DPI')
        self.client.post(reverse('turni:documenti'), {'documento': d.pk, 'dopo': reverse('turni:miei_turni')})
        self.assertTrue(PresaVisione.objects.filter(documento=d, dipendente=self.verdi).exists())
        self.client.get(reverse('turni:miei_turni'))  # la prima volta mostra il messaggio «Presa visione confermata»
        self.assertNotContains(self.client.get(reverse('turni:miei_turni')), 'Regolamento DPI')
        self.client.force_login(self.uff)
        self.assertContains(self.client.get(reverse('turni:documento_ufficio', args=[d.pk])), 'Presa visione · 1 su 2')

    def test_file_non_valido_rifiutato(self):
        self.client.force_login(self.uff)
        finto = SimpleUploadedFile('virus.pdf', b'MZ\x90\x00 non un pdf', content_type='application/pdf')
        self.client.post(reverse('turni:documenti_ufficio'), {'titolo': 'X', 'tipo': 'ALTRO', 'a_chi': 'tutti', 'file': finto})
        self.assertFalse(Documento.objects.exists())


@override_settings(PUSH_SINCRONO=True)
class CalendarioTest(TestCase):
    def setUp(self):
        from datetime import datetime, time

        from .models import Comunicazione, Riunione

        U = get_user_model()
        self.uff = U.objects.create_user('uff', is_staff=True)
        self.op = Dipendente.objects.create(nome='ROSSI MARIO', utente=U.objects.create_user('rossi'))
        self.giorno = timezone.localdate() + timedelta(days=2)
        inizio = timezone.make_aware(datetime.combine(self.giorno, time(10)))
        Riunione.objects.create(titolo='Riunione sicurezza', inizio=inizio, fine=inizio + timedelta(hours=1), creata_da=self.uff)
        Comunicazione.objects.create(tipo='FERMO', testo='Cambio rulli', luogo='IMP1', fascia='1T', dal=inizio,
                                     al=inizio + timedelta(hours=3), motivo='MANUTENZIONE', autore=self.uff)
        Scadenza.objects.create(dipendente=self.op, tipo='VISITA', scade_il=self.giorno)

    def test_home_senza_tutte_le_funzioni_e_con_calendario(self):
        self.client.force_login(self.uff)
        r = self.client.get(reverse('turni:home'))
        self.assertNotContains(r, 'Tutte le funzioni')
        self.assertNotContains(r, 'Prossima riunione')
        self.assertContains(r, reverse('turni:calendario'))

    def test_il_giorno_mostra_riunione_fermo_e_scadenza(self):
        self.client.force_login(self.uff)
        r = self.client.get(reverse('turni:calendario'), {'mese': f'{self.giorno:%Y-%m}', 'giorno': self.giorno.isoformat()})
        for t in ('Riunione sicurezza', 'Impianto 1 fermo', 'Visita medica · Rossi'):
            self.assertContains(r, t)

    def test_operaio_non_vede_il_calendario(self):
        self.client.force_login(self.op.utente)
        self.assertEqual(self.client.get(reverse('turni:calendario')).status_code, 403)


@override_settings(PUSH_SINCRONO=True)
class UfficioNuovoTest(TestCase):
    def setUp(self):
        from django.contrib.auth.models import Permission

        U = get_user_model()
        self.uff = U.objects.create_user('uff', is_staff=True)
        self.uff.user_permissions.add(Permission.objects.get(codename='approva_richieste'))
        self.op = Dipendente.objects.create(nome='ROSSI MARIO', utente=U.objects.create_user('rossi'))
        self.nuovo = Dipendente.objects.create(nome='BIANCHI LUCA')
        self.client.force_login(self.uff)

    def test_ritardo_va_convalidato_con_conferma(self):
        from .models import AvvisoAssenza

        a = AvvisoAssenza.objects.create(dipendente=self.op, data=timezone.localdate(), tipo='RITARDO')
        r = self.client.get(reverse('turni:ufficio_richieste'))
        self.assertContains(r, 'Rossi')
        self.assertContains(r, reverse('turni:ufficio_richiesta_scelta', args=['avviso', a.pk, 'rifiuta']))
        self.client.post(reverse('turni:ufficio_richiesta_scelta', args=['avviso', a.pk, 'rifiuta']), {'nota': 'non avvisato'})
        a.refresh_from_db()
        self.assertEqual(a.esito, 'rifiutato')
        self.assertNotContains(self.client.get(reverse('turni:ufficio_richiesta_scelta', args=['avviso', a.pk, 'approva']), follow=True),
                               'Sì, approva')  # già decisa

    def test_attiva_e_disattiva_accesso(self):
        self.client.post(reverse('turni:accessi'), {'azione': 'attiva', 'dipendente': self.nuovo.pk, 'ruolo': 'UFFICIO'})  # ruoli del 13/11/2026
        self.nuovo.refresh_from_db()
        self.assertIsNotNone(self.nuovo.utente)
        self.assertEqual(self.nuovo.ruolo_app, 'RESP_TURNI')
        self.client.post(reverse('turni:accessi'), {'azione': 'disattiva', 'dipendente': self.nuovo.pk})
        self.nuovo.utente.refresh_from_db()
        self.assertFalse(self.nuovo.utente.is_active)

    def test_anagrafica_e_pdf(self):
        r = self.client.get(reverse('turni:anagrafica'), {'dip': self.op.pk})
        for t in ('Data di nascita', 'Ferie residue', 'Ritardi su ingressi', 'Turni notturni'):
            self.assertContains(r, t)
        self.client.post(reverse('turni:anagrafica') + f'?dip={self.op.pk}', {'data_nascita': '1990-05-01', 'data_assunzione': '2020-02-03'})
        self.op.refresh_from_db()
        self.assertEqual(str(self.op.data_assunzione), '2020-02-03')
        pdf = self.client.get(reverse('turni:anagrafica_pdf', args=[self.op.pk]))
        self.assertEqual(pdf['Content-Type'], 'application/pdf')

    def test_richiedi_turno_extra_avvisa_gli_operai(self):
        from .models import Notifica, TurnoExtra

        self.client.post(reverse('turni:ufficio_extra_nuovo'), {'data': timezone.localdate().isoformat(), 'fascia': '1T',
                                                                'postazione': 'IMP1', 'posti': '2'})
        self.assertEqual(TurnoExtra.objects.get().posti, 2)
        self.assertTrue(Notifica.objects.filter(utente=self.op.utente, titolo='Cercasi turno extra').exists())
        self.assertContains(self.client.get(reverse('turni:ufficio_turni')), 'Mancano 2 su 2')


class ElencoDipendentiTest(TestCase):
    """Elenco dipendenti dal foglio «Elenco Dipendenti, Aree e Orari» e accesso per tutti (nomi inventati)."""

    def file(self):
        from io import BytesIO

        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Elenco Dipendenti, Aree e Orari'
        ws.append([None, None, None, 1, 1])
        ws.append([None, None, 'Dipendenti', 'RI', 'RP'])
        for i, nome in enumerate(['ROSSI MARIO', 'VERDI ANNA', 'NERI PAOLO'], 1):
            ws.append([None, i, nome, 1, None])
        buf = BytesIO()
        wb.save(buf)
        return SimpleUploadedFile('Organizzazione_Turni.xlsx', buf.getvalue())

    def test_carica_elenco_e_accesso_per_tutti(self):
        U = get_user_model()
        Dipendente.objects.create(nome="ROSSI MARIO")
        self.client.force_login(U.objects.create_user('uff', is_staff=True))
        r = self.client.post(reverse('turni:accessi'), {'azione': 'elenco', 'file': self.file()}, follow=True)
        self.assertContains(r, 'Elenco aggiornato')
        nomi = set(Dipendente.objects.values_list('nome', flat=True))
        self.assertTrue({'NERI PAOLO', 'ROSSI MARIO', 'VERDI ANNA'} <= nomi)
        self.assertEqual(Dipendente.objects.filter(nome='ROSSI MARIO').count(), 1)  # chi c'era già non si duplica
        r = self.client.post(reverse('turni:accessi'), {'azione': 'tutti'})
        self.assertRedirects(r, reverse('turni:credenziali'), fetch_redirect_response=False)
        self.assertFalse(Dipendente.objects.filter(utente__isnull=True).exists())


class MacchineOtticheTest(TestCase):
    """Regole dell'11/11/2026: ottiche a due OdL competenti (MO 1, poi 2), pavimentazione agli altri, CT senza pulizie."""

    def test_ottiche_e_pavimentazione(self):
        from .models import Pulizia, Settimana, Turno
        from .pulizie import genera_pulizie

        giorno = timezone.localdate() + timedelta(days=1)
        while giorno.weekday() in (2, 5):  # niente controllo vagli, per non confondere il conteggio
            giorno += timedelta(days=1)
        sett, _ = Settimana.objects.get_or_create(lunedi=giorno - timedelta(days=giorno.weekday()))
        persone = [('ODL UNO', 1, False), ('ODL DUE', 2, False), ('ODL TRE', 2, False), ('ODL QUATTRO', None, False), ('CAPO PROVA', 1, True)]
        turni = {}
        for nome, mo, capo in persone:
            d = Dipendente.objects.create(nome=nome, livello_mo=mo)
            turni[nome] = Turno.objects.create(settimana=sett, dipendente=d, data=giorno, fascia='1T', postazione='IMP1',
                                               capoturno=capo, ruolo='CT' if capo else 'OdL',
                                               incarichi='IMP1/CT' if capo else 'IMP1/OdL')
        for t in turni.values():
            genera_pulizie(t)
        ottiche = set(Pulizia.objects.filter(elemento__nome='Macchine ottiche', turno__data=giorno).values_list('turno__dipendente__nome', flat=True))
        pavimento = set(Pulizia.objects.filter(elemento__nome='Pavimentazione + altro', turno__data=giorno).values_list('turno__dipendente__nome', flat=True))
        self.assertEqual(len(ottiche), 2)
        self.assertIn('ODL UNO', ottiche)  # chi ha 1 viene prima
        self.assertNotIn('ODL QUATTRO', ottiche)  # senza MO non le fa
        self.assertEqual(ottiche | pavimento, {'ODL UNO', 'ODL DUE', 'ODL TRE', 'ODL QUATTRO'})
        self.assertFalse(ottiche & pavimento)
        self.assertFalse(turni['CAPO PROVA'].pulizie.exists())  # il Capo Turno supervisiona
