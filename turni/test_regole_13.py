"""Regole del documento «Controllo app» confermate da Giulia il 13/11/2026."""

from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import Dipendente, Mansione, Notifica, Pulizia, RuoloApp, Settimana, Straordinaria, Turno
from .pulizie import genera_pulizie


def foto():
    b = BytesIO()
    Image.new('RGB', (20, 20), 'red').save(b, 'JPEG')
    return SimpleUploadedFile('f.jpg', b.getvalue(), content_type='image/jpeg')


@override_settings(PUSH_SINCRONO=True)
class RegoleTest(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.sett = Settimana.objects.create(lunedi=self.oggi - timedelta(days=self.oggi.weekday()))

    def dip(self, nome, **campi):
        d = Dipendente.objects.create(nome=nome, **campi)
        d.utente = get_user_model().objects.create_user(nome.lower().replace(' ', '.'))
        d.save()
        return d

    def turno(self, d, fascia='1T', postazione='IMP1', ruolo='OdL', capoturno=False, posto='Impianto 1 · Operatore di Linea'):
        return Turno.objects.create(settimana=self.sett, dipendente=d, data=self.oggi, fascia=fascia, postazione=postazione,
                                    ruolo='CT' if capoturno else ruolo, capoturno=capoturno, posto=posto,
                                    incarichi=f'{postazione}/{"CT" if capoturno else ruolo}')

    def test_operaio_chiede_al_rp_che_approva_e_assegna(self):
        op = self.dip('ROSSI MARIO')
        self.turno(op)
        ct = self.dip('GALLI RINO')
        t_ct = self.turno(ct, capoturno=True, posto='Impianto 1 · Capo Turno')
        rp = self.dip('LOMBARDI GINO', resp_piazzale=True)
        self.client.force_login(op.utente)
        self.assertContains(self.client.get(reverse('turni:pulizie')), 'Richiedi pulizia')
        url = reverse('turni:richiedi_pulizia') + f'?area=IMP1&giorno={self.oggi.isoformat()}&fascia=1T'
        r = self.client.get(url)
        self.assertContains(r, 'Manda al responsabile piazzale')
        self.assertNotContains(r, 'A chi la assegni?')
        self.client.post(url, {'area': 'IMP1', 'giorno': self.oggi.isoformat(), 'fascia': '1T', 'nota': 'Olio sotto il nastro', 'foto': foto()})
        s = Straordinaria.objects.get()
        self.assertEqual((s.tipo, s.stato), (Straordinaria.Tipo.RICHIESTA, Straordinaria.Stato.ATTESA))
        self.assertFalse(Pulizia.objects.filter(richiesta_da__isnull=False).exists())
        self.assertTrue(Notifica.objects.filter(utente=rp.utente, tipo='straordinaria', oggetto_id=s.pk).exists())
        # il RP la vede nella sua pagina, sceglie a chi darla (proposto il Capo Turno) e la approva
        self.client.force_login(rp.utente)
        self.assertContains(self.client.get(reverse('turni:pulizie_piazzale')), 'Richieste da approvare')
        r = self.client.get(reverse('turni:richiesta_rp', args=[s.pk]))
        self.assertContains(r, f'value="{t_ct.pk}" selected')
        self.client.post(reverse('turni:richiesta_rp', args=[s.pk]), {'azione': 'approva', 'turno': t_ct.pk})
        p = t_ct.pulizie.get()
        self.assertIn('Olio sotto il nastro', p.nota)
        self.assertTrue(p.foto_richiesta)
        self.assertTrue(Notifica.objects.filter(utente=op.utente, titolo__contains='approvata').exists())

    def test_rp_rifiuta_e_chi_chiede_viene_avvisato(self):
        op = self.dip('ROSSI MARIO')
        rp = self.dip('LOMBARDI GINO', resp_piazzale=True)
        from .pulizie import chiedi_al_rp

        s = chiedi_al_rp(op.utente, Straordinaria.Tipo.STRAORDINARIA, 'IMP2', self.oggi, '2T', 'Lavaggio tramoggia')
        self.client.force_login(rp.utente)
        self.client.post(reverse('turni:richiesta_rp', args=[s.pk]), {'azione': 'rifiuta', 'nota': 'Già fatta ieri'})
        s.refresh_from_db()
        self.assertEqual(s.stato, Straordinaria.Stato.RIFIUTATA)
        self.assertTrue(Notifica.objects.filter(utente=op.utente, testo__contains='Già fatta ieri').exists())

    def test_il_rp_assegna_direttamente(self):
        rp = self.dip('LOMBARDI GINO', resp_piazzale=True)
        op = self.dip('ROSSI MARIO')
        t = self.turno(op)
        self.client.force_login(rp.utente)
        url = reverse('turni:richiedi_pulizia') + f'?area=IMP1&giorno={self.oggi.isoformat()}&fascia=1T'
        self.assertContains(self.client.get(url), 'A chi la assegni?')
        self.client.post(url, {'area': 'IMP1', 'giorno': self.oggi.isoformat(), 'fascia': '1T', 'turno': t.pk, 'foto': foto()})
        self.assertTrue(t.pulizie.exists())
        self.assertFalse(Straordinaria.objects.exists())

    def test_ottiche_solo_il_capo_turno(self):
        a = self.dip('ROSSI MARIO', livello_mo=1)
        ta = self.turno(a)
        man = self.dip('NERI UGO', mansione=Mansione.MANUTENTORE)
        self.turno(man, ruolo='Man', postazione='MANUT', posto='Manutenzione · Manutentore')
        genera_pulizie(ta)
        p = ta.pulizie.get(elemento__nome='Macchine ottiche')
        url = reverse('turni:pulizia_voce', args=[p.pk])
        for chi in (a, man):
            self.client.force_login(chi.utente)
            self.assertNotContains(self.client.get(url), 'Pulizia ottiche iniziata')
            self.client.post(url, {'azione': 'iniziata'})
            self.client.post(url, {'azione': 'manutentore', 'fatto': '1'})
        p.refresh_from_db()
        self.assertIsNone(p.iniziata_il)
        self.assertIsNone(p.ok_manutentore_il)
        ct = self.dip('GALLI RINO')
        self.turno(ct, capoturno=True, posto='Impianto 1 · Capo Turno')
        self.client.force_login(ct.utente)
        self.assertContains(self.client.get(url), 'Pulizia ottiche iniziata')

    def test_ufficio_non_verifica_ne_convalida(self):
        u = get_user_model().objects.create_user('ufficio.prova', is_staff=True)
        self.client.force_login(u)
        self.assertEqual(self.client.get(reverse('turni:capoturno')).status_code, 403)
        self.assertEqual(self.client.get(reverse('turni:pulizie_piazzale')).status_code, 403)
        r = self.client.get(reverse('turni:pulizie'))
        self.assertNotContains(r, 'Da convalidare')
        self.assertNotContains(r, 'Da verificare')
        self.assertContains(r, 'Calendario pulizie')

    def test_da_verificare_righe_apribili_e_in_attesa_del_rp(self):
        a = self.dip('ROSSI MARIO')
        ta = self.turno(a)
        genera_pulizie(ta)
        ct = self.dip('GALLI RINO')
        self.turno(ct, capoturno=True, posto='Impianto 1 · Capo Turno')
        self.client.force_login(ct.utente)
        r = self.client.get(reverse('turni:capoturno'))
        self.assertContains(r, '<h1>Da verificare</h1>')
        self.assertContains(r, reverse('turni:pulizia_voce', args=[ta.pulizie.first().pk]))
        p = ta.pulizie.first()
        p.stato, p.ok_capoturno_il = Pulizia.Stato.FATTA, timezone.now()
        p.save()
        self.assertContains(self.client.get(reverse('turni:capoturno')), 'In attesa del RP')

    def test_operaio_impianto_1_senza_pulizia_aggiuntiva(self):
        a = self.dip('ROSSI MARIO')
        self.turno(a)
        self.client.force_login(a.utente)
        self.assertNotContains(self.client.get(reverse('turni:pulizie')), 'Pulizia aggiuntiva completata')
        b = self.dip('COSTA DINO')
        self.turno(b, postazione='IMP2', posto='Impianto 2 - I · Operatore di Linea')
        self.client.force_login(b.utente)
        self.assertContains(self.client.get(reverse('turni:pulizie')), 'Pulizia aggiuntiva completata')

    def test_turni_di_tutti_per_dipendente_e_per_area(self):
        a = self.dip('ROSSI MARIO')
        self.turno(a)
        ct = self.dip('GALLI RINO')
        self.turno(ct, capoturno=True, posto='Impianto 1 · Capo Turno')
        self.client.force_login(a.utente)
        r = self.client.get(reverse('turni:settimana_tutti'))
        self.assertContains(r, 'Per Dipendente')
        self.assertContains(r, '1T | Impianto 1 | CT')
        self.assertContains(r, 'vp-io')
        r = self.client.get(reverse('turni:settimana_tutti') + '?vista=area')
        self.assertContains(r, 'Impianto 1</th>', count=1)
        self.assertContains(r, '<td class="vp-ruolo">CT</td>')
        self.assertNotContains(self.client.get(reverse('turni:menu')), reverse('turni:squadra'))

    def test_direzione_e_amministrazione_home_ufficio(self):
        d = self.dip('SANTORO ANTONIO', ruolo_app=RuoloApp.DIREZIONE)
        self.client.force_login(d.utente)
        r = self.client.get(reverse('turni:home'))
        self.assertContains(r, 'hu-sezione')
        self.assertContains(r, reverse('turni:calendario'))  # eventi di tutti
        self.assertContains(r, reverse('turni:riunioni'))
        amm = self.dip('SPINA ALICE', ruolo_app=RuoloApp.AMMINISTRAZIONE)
        self.client.force_login(amm.utente)
        r = self.client.get(reverse('turni:home'))
        self.assertContains(r, 'hu-sezione')
        self.assertNotContains(r, reverse('turni:accessi'))
        self.assertNotContains(r, reverse('turni:importa'))

    def test_archivio_torna_alla_home(self):
        a = self.dip('ROSSI MARIO')
        self.client.force_login(a.utente)
        r = self.client.get(reverse('turni:archivio'))
        self.assertContains(r, f'class="tasto-indietro" href="{reverse("turni:home")}"')

    def test_da_rifare_del_rp_rosso_pastello(self):
        rp = self.dip('LOMBARDI GINO', resp_piazzale=True)
        a = self.dip('COSTA DINO')
        t = self.turno(a, postazione='IMP2', posto='Impianto 2 - I · Operatore di Linea')
        genera_pulizie(t)
        p = t.pulizie.first()
        p.stato, p.fatta_il = Pulizia.Stato.FATTA, timezone.now()
        p.save()
        self.client.force_login(rp.utente)
        self.assertContains(self.client.get(reverse('turni:pulizie_piazzale')), 'class="bottone rifiuta" name="azione" value="rifare"')


class RuoliAccessoTest(TestCase):
    """Gestione accessi: Responsabile Impianto, Responsabile Piazzale, Operaio, Manutentore, Ufficio (Giulia, 13/11/2026)."""

    def setUp(self):
        hr = Dipendente.objects.create(nome='ANCORA MARTA', ruolo_app=RuoloApp.RESP_TURNI)
        hr.utente = get_user_model().objects.create_user('hr.prova', is_staff=True)
        hr.save()
        self.client.force_login(hr.utente)

    def attiva(self, nome, ruolo, ufficio=''):
        d = Dipendente.objects.create(nome=nome)
        self.client.post(reverse('turni:accessi'), {'azione': 'attiva', 'dipendente': d.pk, 'ruolo': ruolo, 'ufficio': ufficio})
        d.refresh_from_db()
        return d

    def test_ruoli(self):
        r = self.client.get(reverse('turni:accessi'))
        for testo in ('Responsabile Impianto', 'Responsabile Piazzale', 'Operaio (OdL e Capo Turno)', 'Manutentore', 'Ufficio', 'Quale ufficio'):
            self.assertContains(r, testo)
        self.assertTrue(self.attiva('MARINO LEO', 'RI').resp_impianto)
        self.assertTrue(self.attiva('LOMBARDI GINO', 'RP').resp_piazzale)
        self.assertIn('MANUTENTORE', self.attiva('NERI UGO', 'MAN').mansioni)
        op = self.attiva('ROSSI MARIO', 'OPERAIO')
        self.assertEqual((op.ruolo_app, op.resp_impianto, op.resp_piazzale), ('OPERAIO', False, False))
        hr = self.attiva('VERDI ANNA', 'UFFICIO', 'RESP_TURNI')
        self.assertTrue(hr.utente.is_staff)
        d = self.attiva('SANTORO ANTONIO', 'UFFICIO', 'DIREZIONE')
        self.assertEqual(d.ruolo_app, 'DIREZIONE')
        self.assertFalse(d.utente.is_staff)
        self.assertEqual(self.attiva('SPINA ALICE', 'UFFICIO', 'AMMINIS').ruolo_accesso, 'Ufficio · Amministrazione')
