"""Pulizie per tutti (Giulia, 12/11/2026): programma per giorno e settimana, «In corso adesso», scheda della pulizia,
avvisi automatici (ottiche, pozzetti, vagli, Incolore, carrelli) e straordinarie del responsabile impianto."""

from datetime import date, datetime, timedelta
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from . import piano_pulizie as pp
from .models import Dipendente, ElementoPulizia, Mansione, Notifica, Pulizia, Settimana, Straordinaria, Turno
from .pulizie import genera_pulizie

LUNEDI = date(2026, 11, 2)
MERCOLEDI = LUNEDI + timedelta(days=2)
SABATO = LUNEDI + timedelta(days=5)


def alle(ore, minuti=0, giorno=LUNEDI):
    return timezone.make_aware(datetime.combine(giorno, datetime.min.time()) + timedelta(hours=ore, minutes=minuti))


def foto():
    b = BytesIO()
    Image.new('RGB', (20, 20), 'red').save(b, 'JPEG')
    return SimpleUploadedFile('f.jpg', b.getvalue(), content_type='image/jpeg')


@override_settings(PUSH_SINCRONO=True)
class PianoPulizieTest(TestCase):
    def setUp(self):
        self.sett = Settimana.objects.create(lunedi=LUNEDI)
        self.adesso = alle(9)
        patcher = mock.patch('django.utils.timezone.now', side_effect=lambda: self.adesso)
        patcher.start()
        self.addCleanup(patcher.stop)

    def persona(self, nome, fascia='1T', postazione='IMP1', ruolo='OdL', capoturno=False, giorno=LUNEDI, **campi):
        d = Dipendente.objects.filter(nome=nome).first()
        if d is None:
            d = Dipendente.objects.create(nome=nome, **campi)
            d.utente = get_user_model().objects.create_user(nome.lower().replace(' ', ''), password='123456')
            d.save()
        return Turno.objects.create(settimana=self.sett, dipendente=d, data=giorno, fascia=fascia, postazione=postazione,
                                    capoturno=capoturno, ruolo='CT' if capoturno else ruolo)

    def entra(self, turno_o_dip):
        dip = getattr(turno_o_dip, 'dipendente', turno_o_dip)
        self.client.force_login(dip.utente)

    def notifiche(self, turno):
        return list(Notifica.objects.filter(utente=turno.dipendente.utente).values_list('titolo', flat=True))

    # ---------------------------------------------------------------- viste

    def test_programma_giorno_settimana_e_adesso(self):
        a = self.persona('Rossi Mario', livello_mo=1)
        self.persona('Bianchi Luca', livello_mo=2)
        self.persona('Galli Rino', capoturno=True)
        self.persona('Fontana Elio', 'G', 'MULINO')
        self.entra(a)
        r = self.client.get(reverse('turni:pulizie_programma') + f'?giorno={LUNEDI.isoformat()}')
        self.assertContains(r, 'Macchine ottiche')
        self.assertContains(r, 'Bianchi L')
        self.assertContains(r, 'Giornaliero · 8–17:30')
        self.assertContains(r, 'Mulino e pressa')
        self.assertContains(r, 'a metà turno')
        self.assertContains(r, 'f-mattina')
        # i giorni futuri si calcolano dalle regole, senza scrivere le pulizie
        domani = self.persona('Rossi Mario', giorno=LUNEDI + timedelta(days=1))
        prima = Pulizia.objects.count()
        r = self.client.get(reverse('turni:pulizie_programma') + f'?giorno={domani.data.isoformat()}')
        self.assertContains(r, 'Macchine ottiche')
        self.assertEqual(Pulizia.objects.count(), prima)
        r = self.client.get(reverse('turni:pulizie_programma') + f'?vista=settimana&giorno={LUNEDI.isoformat()}')
        self.assertContains(r, 'pp-tabella')
        self.assertContains(r, '2 – 8 novembre')
        r = self.client.get(reverse('turni:pulizie_adesso'))
        self.assertContains(r, 'ADESSO')
        self.assertContains(r, 'Giornaliero')
        testo = r.content.decode()
        # ordine 1T, 2T, G, N (Giulia, 12/11)
        self.assertLess(testo.index('1° turno · 6–14'), testo.index('2° turno · 14–22'))
        self.assertLess(testo.index('2° turno · 14–22'), testo.index('Giornaliero · 8–17:30'))
        self.assertLess(testo.index('Giornaliero · 8–17:30'), testo.index('Notturno · 22–6'))
        # i tasti nella pagina Pulizia, per tutti
        r = self.client.get(reverse('turni:pulizie'))
        self.assertContains(r, reverse('turni:pulizie_programma'))
        self.assertContains(r, reverse('turni:pulizie_adesso'))

    # ---------------------------------------------------------------- macchine ottiche

    def test_ottiche_avviso_a_meta_turno_poi_iniziata_spunta_e_conclusa(self):
        a = self.persona('Rossi Mario', livello_mo=1)
        b = self.persona('Bianchi Luca', livello_mo=1)
        ct = self.persona('Galli Rino', capoturno=True)
        man = self.persona('Neri Ugo', ruolo='Man', mansione=Mansione.MANUTENTORE)
        self.adesso = alle(9, 59)
        pp.controlla()  # parte solo quello dei pozzetti (entro le 7)
        self.assertFalse(any('ottiche' in t for t in self.notifiche(ct)))
        self.adesso = alle(10)
        self.assertEqual(pp.controlla(), 1)
        self.assertEqual(pp.controlla(), 0)  # una volta sola
        self.assertTrue(any('Macchine ottiche: è metà turno' in t for t in self.notifiche(ct)))
        self.assertTrue(any('metà turno' in t for t in self.notifiche(man)))
        self.assertFalse(self.notifiche(a))
        # nel centro notifiche c'è il tasto «Pulizia ottiche iniziata»
        self.entra(ct)
        self.assertContains(self.client.get(reverse('turni:notifiche')), 'Pulizia ottiche iniziata')
        p = Pulizia.objects.filter(elemento__nome='Macchine ottiche', turno=a).get()
        url = reverse('turni:pulizia_voce', args=[p.pk])
        self.client.post(url, {'azione': 'iniziata'})
        self.assertEqual(Pulizia.objects.filter(elemento__nome='Macchine ottiche', iniziata_il__isnull=False).count(), 2)
        self.assertContains(self.client.get(reverse('turni:pulizie_programma') + f'?giorno={LUNEDI.isoformat()}'), 'In corso')
        # «Conclusa» solo dopo la spunta del manutentore
        self.client.post(url, {'azione': 'conclusa'})
        self.assertEqual(Pulizia.objects.filter(elemento__nome='Macchine ottiche', stato=Pulizia.Stato.FATTA).count(), 0)
        self.entra(man)
        self.client.post(url, {'azione': 'manutentore', 'fatto': '1'})
        self.entra(ct)
        self.client.post(url, {'azione': 'conclusa'})
        righe = Pulizia.objects.filter(elemento__nome='Macchine ottiche')
        self.assertEqual({r.stato for r in righe}, {Pulizia.Stato.FATTA})
        self.assertTrue(all(pp.va_al_rp(r) for r in righe))
        self.assertEqual(pp.stato_di(righe[0]), 'rp')
        del b

    # ---------------------------------------------------------------- pozzetti

    def test_pozzetti_alle_7_chiede_al_capo_turno_che_puo_cambiare_nome(self):
        a = self.persona('Rossi Mario')
        b = self.persona('Bianchi Luca')
        ct = self.persona('Galli Rino', capoturno=True)
        self.adesso = alle(7)
        pp.controlla()
        self.assertTrue(any('Pozzetti: sono stati puliti?' in t for t in self.notifiche(ct)))
        p = Pulizia.objects.get(elemento__nome='Pozzetti')
        altro = b if p.turno == a else a
        self.entra(ct)
        r = self.client.get(reverse('turni:pulizia_voce', args=[p.pk]))
        self.assertContains(r, 'Fatta da')
        self.assertContains(r, 'Non ancora')
        self.client.post(reverse('turni:pulizia_voce', args=[p.pk]), {'azione': 'conferma', 'fatta_da': altro.dipendente_id})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.FATTA)
        self.assertEqual(p.fatta_da, altro.dipendente)
        self.assertTrue(pp.va_al_rp(p))
        self.assertContains(self.client.get(reverse('turni:pulizie_programma') + f'?giorno={LUNEDI.isoformat()}'),
                            altro.dipendente.nome_breve)

    def test_pozzetti_gia_fatti_niente_avviso(self):
        self.persona('Rossi Mario')
        ct = self.persona('Galli Rino', capoturno=True)
        for t in Turno.objects.all():
            genera_pulizie(t)
        Pulizia.objects.filter(elemento__nome='Pozzetti').update(stato=Pulizia.Stato.FATTA, fatta_il=alle(6, 40))
        self.adesso = alle(7, 5)
        pp.controlla()
        self.assertFalse(any('Pozzetti' in t for t in self.notifiche(ct)))

    # ---------------------------------------------------------------- vagli, Incolore, carrelli

    def test_vagli_45_minuti_prima_della_fine(self):
        ct = self.persona('Galli Rino', capoturno=True, giorno=MERCOLEDI)
        man = self.persona('Neri Ugo', ruolo='Man', mansione=Mansione.MANUTENTORE, giorno=MERCOLEDI)
        self.persona('Rossi Mario', giorno=MERCOLEDI)
        self.adesso = alle(13, 14, MERCOLEDI)
        pp.controlla()
        self.assertFalse(any('vagli' in t.lower() for t in self.notifiche(ct)))
        self.adesso = alle(13, 15, MERCOLEDI)
        pp.controlla()
        self.assertTrue(any('Controllo vagli zig-zag: mancano 45 minuti' in t for t in self.notifiche(ct)))
        self.assertTrue(any('mancano 45 minuti' in t for t in self.notifiche(man)))

    def test_incolore_un_ora_e_un_quarto_prima_all_operatore_dell_impianto_2(self):
        op = self.persona('Costa Dino', postazione='IMP2')
        ct = self.persona('Galli Rino', capoturno=True)
        self.adesso = alle(12, 45)
        pp.controlla()
        self.assertTrue(any('Incolore: mancano 75 minuti' in t for t in self.notifiche(op)))
        self.assertFalse(any('Incolore' in t for t in self.notifiche(ct)))
        p = Pulizia.objects.get(elemento__nome='Incolore')
        self.assertTrue(p.disponibile)
        self.assertEqual(pp.percorso(p), 'PIAZZALE')  # la manda lui al responsabile piazzale

    def test_carrelli_sabato_alle_16_ai_manutentori(self):
        man = self.persona('Neri Ugo', '2T', 'MANUT', ruolo='', mansione=Mansione.MANUTENTORE, giorno=SABATO)
        self.adesso = alle(15, 59, SABATO)
        pp.controlla()
        self.assertFalse(self.notifiche(man))
        self.adesso = alle(16, 0, SABATO)
        pp.controlla()
        self.assertTrue(any('Carrelli elevatori' in t for t in self.notifiche(man)))

    def test_avvisi_nell_amministrazione_dalla_migrazione(self):
        e = ElementoPulizia.objects.get(nome='Macchine ottiche')
        self.assertEqual((e.avviso, e.avviso_a, e.con_avvio), ('META', 'CT_MAN', True))
        self.assertEqual(ElementoPulizia.objects.get(nome='Pozzetti').avviso_ora.hour, 7)
        self.assertEqual(ElementoPulizia.objects.get(nome='Incolore').minuti_prima_fine, 75)
        self.assertEqual(ElementoPulizia.objects.get(nome='Generiche Sabbia Superbi').convalida, 'PIAZZALE')

    # ---------------------------------------------------------------- straordinarie

    def test_straordinaria_del_ri_passa_dal_rp_poi_al_capo_turno(self):
        ri = Dipendente.objects.create(nome='Marchese Leo', resp_impianto=True)
        ri.utente = get_user_model().objects.create_user('ri', password='123456')
        ri.save()
        rp = Dipendente.objects.create(nome='Lombardo Gabri', resp_piazzale=True)
        rp.utente = get_user_model().objects.create_user('rp', password='123456')
        rp.save()
        ct = self.persona('Galli Rino', capoturno=True, giorno=LUNEDI + timedelta(days=1))
        self.client.force_login(ri.utente)
        self.client.post(reverse('turni:programma', args=['pulizia']), {
            'luogo': 'IMP1', 'descrizione': 'Pulire sotto il nastro', 'giorno': (LUNEDI + timedelta(days=1)).isoformat(), 'turno': '1T'})
        s = Straordinaria.objects.get()
        self.assertEqual(s.stato, Straordinaria.Stato.ATTESA)
        self.assertFalse(ct.pulizie.exists())
        self.assertTrue(Notifica.objects.filter(utente=rp.utente, tipo='straordinaria').exists())
        self.client.force_login(rp.utente)
        self.client.post(reverse('turni:notifica_scelta', args=['straordinaria', s.pk, 'conferma']))
        s.refresh_from_db()
        self.assertEqual(s.stato, Straordinaria.Stato.INOLTRATA)
        p = ct.pulizie.get()
        self.assertIn('Pulire sotto il nastro', p.nota)
        # il Capo Turno la fa e la conferma con la foto: va direttamente al responsabile piazzale
        self.adesso = alle(9, 0, LUNEDI + timedelta(days=1))
        self.entra(ct)
        self.client.post(reverse('turni:pulizia_voce', args=[p.pk]), {'azione': 'conferma', 'foto': foto()})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.FATTA)
        self.assertTrue(pp.va_al_rp(p))
        from .pulizie import da_convalidare_piazzale

        self.assertIn(p, list(da_convalidare_piazzale()))

    def test_dipendente_non_capo_non_conferma_per_gli_altri(self):
        a = self.persona('Rossi Mario')
        b = self.persona('Bianchi Luca')
        genera_pulizie(a)
        p = a.pulizie.first()
        self.entra(b)
        r = self.client.get(reverse('turni:pulizia_voce', args=[p.pk]))
        self.assertNotContains(r, 'name="azione" value="conferma"')
        self.client.post(reverse('turni:pulizia_voce', args=[p.pk]), {'azione': 'conferma'})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.DA_FARE)
