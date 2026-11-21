"""Pulizie per tutti (Giulia, 12/11/2026): programma per giorno e settimana, «In corso adesso», scheda della pulizia,
avvisi automatici e straordinarie del responsabile impianto. Dal 21/11/2026 le regole sono quelle del file
«Regole Pulizie - unico.xlsx»: avvisi con 3 tasti, ripetuti ogni 15 minuti, Non eseguita a fine turno, più foto e video."""

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
        self.assertContains(r, 'dopo metà turno')
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

    def messaggi(self, turno):
        return list(Notifica.objects.filter(utente=turno.dipendente.utente).values_list('testo', flat=True))

    # ---------------------------------------------------------------- macchine ottiche

    def test_ottiche_avviso_dopo_meta_turno_poi_iniziata_e_conclusa_senza_manutentore(self):
        a = self.persona('Rossi Mario', livello_mo=1)
        self.persona('Bianchi Luca', livello_mo=1)
        ct = self.persona('Galli Rino', capoturno=True)
        man = self.persona('Neri Ugo', ruolo='Man', mansione=Mansione.MANUTENTORE)
        self.adesso = alle(10, 14)
        pp.controlla()  # partono solo i pozzetti (60 minuti dopo l'inizio)
        self.assertFalse(any('ottiche' in t for t in self.notifiche(ct)))
        self.adesso = alle(10, 15)  # 15 minuti dopo metà turno (file del 21/11/2026)
        self.assertEqual(pp.controlla(), 1)
        self.assertEqual(pp.controlla(), 0)  # la ripetizione arriva solo dopo 15 minuti
        self.assertIn('🔔 Macchine ottiche - metà turno', self.notifiche(ct))
        self.assertIn('Sono passati 15 min da metà turno: completa la pulizia.', self.messaggi(ct))
        self.assertFalse(any('ottiche' in t for t in self.notifiche(man)))  # avviso solo al Capo Turno
        self.assertFalse(self.notifiche(a))
        p = Pulizia.objects.filter(elemento__nome='Macchine ottiche - metà turno', turno=a).get()
        # nel centro notifiche «Rispondi» apre l'avviso con i 3 tasti
        self.entra(ct)
        self.assertContains(self.client.get(reverse('turni:notifiche')), '/turni/pulizie/avviso/')
        r = self.client.get(reverse('turni:avviso_pulizia', args=[p.pk]))
        self.assertContains(r, 'Effettuata')
        self.assertContains(r, 'Non effettuata')
        self.assertContains(r, 'Ricordamelo tra')
        url = reverse('turni:pulizia_voce', args=[p.pk])
        self.assertContains(r, f'href="{url}"')  # Effettuata = la stessa scheda di «Conferma pulizia»
        self.client.post(url, {'azione': 'iniziata'})
        self.assertEqual(Pulizia.objects.filter(elemento__nome='Macchine ottiche - metà turno', iniziata_il__isnull=False).count(), 2)
        self.assertContains(self.client.get(reverse('turni:pulizie_programma') + f'?giorno={LUNEDI.isoformat()}'), 'In corso')
        scheda = self.client.get(url).content.decode()
        self.assertNotIn('Manutentore: completato', scheda)  # niente più check del manutentore
        self.client.post(url, {'azione': 'conclusa'})
        righe = Pulizia.objects.filter(elemento__nome='Macchine ottiche - metà turno')
        self.assertEqual({r.stato for r in righe}, {Pulizia.Stato.FATTA})
        self.assertTrue(all(pp.va_al_rp(r) for r in righe))
        self.assertEqual(pp.stato_di(righe[0]), 'rp')

    def test_ottiche_fine_turno_si_conclude_solo_negli_ultimi_15_minuti(self):
        a = self.persona('Rossi Mario', livello_mo=1)
        self.persona('Bianchi Luca', livello_mo=1)
        ct = self.persona('Galli Rino', capoturno=True)
        genera_pulizie(a)
        p = a.pulizie.get(elemento__nome='Macchine ottiche - fine turno')
        self.entra(ct)
        url = reverse('turni:pulizia_voce', args=[p.pk])
        self.adesso = alle(13, 30)
        self.client.post(url, {'azione': 'iniziata'})
        self.client.post(url, {'azione': 'conclusa'})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.DA_FARE)  # troppo presto: dalle 13:45
        self.adesso = alle(13, 45)
        pp.controlla()
        self.assertIn('Mancano 15 min alla fine del turno: completa la pulizia.', self.messaggi(ct))
        self.client.post(url, {'azione': 'conclusa'})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.FATTA)

    # ---------------------------------------------------------------- pozzetti

    def test_pozzetti_60_minuti_dopo_l_inizio_al_capo_turno_che_puo_cambiare_nome(self):
        a = self.persona('Rossi Mario')
        b = self.persona('Bianchi Luca')
        ct = self.persona('Galli Rino', capoturno=True)
        self.adesso = alle(7)
        pp.controlla()
        self.assertIn('🔔 Pozzetti', self.notifiche(ct))
        self.assertIn("Sono passati 60 min dall'inizio del turno: completa la pulizia.", self.messaggi(ct))
        p = Pulizia.objects.get(elemento__nome='Pozzetti')
        altro = b if p.turno == a else a
        self.entra(ct)
        r = self.client.get(reverse('turni:pulizia_voce', args=[p.pk]))
        self.assertContains(r, 'Fatta da')
        self.assertNotContains(r, 'Non ancora')  # sostituito da «Ricordamelo tra» nell'avviso
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

    def test_vagli_45_minuti_prima_della_fine_tasti_al_manutentore(self):
        ct = self.persona('Galli Rino', capoturno=True, giorno=MERCOLEDI)
        man = self.persona('Neri Ugo', ruolo='Man', mansione=Mansione.MANUTENTORE, giorno=MERCOLEDI)
        self.persona('Rossi Mario', giorno=MERCOLEDI)
        self.adesso = alle(13, 14, MERCOLEDI)
        pp.controlla()
        self.assertFalse(any('vagli' in t.lower() for t in self.notifiche(ct)))
        self.adesso = alle(13, 15, MERCOLEDI)
        pp.controlla()
        self.assertIn('🔔 Controllo vagli zig-zag', self.notifiche(ct))
        self.assertIn('🔔 Controllo vagli zig-zag', self.notifiche(man))
        self.assertIn('Mancano 45 min alla fine del turno: completa il controllo.', self.messaggi(man))
        p = Pulizia.objects.get(elemento__nome='Controllo vagli zig-zag')
        # i tasti li usa chi conferma (il Manutentore); il Capo Turno lo riceve solo per sapere
        self.entra(man)
        self.assertContains(self.client.get(reverse('turni:avviso_pulizia', args=[p.pk])), 'Effettuata')
        self.entra(ct)
        r = self.client.get(reverse('turni:avviso_pulizia', args=[p.pk]))
        self.assertNotContains(r, 'Effettuata')
        self.assertContains(r, 'solo per sapere')

    def test_linea_incolore_75_minuti_prima_all_operatore_dell_impianto_2(self):
        op = self.persona('Costa Dino', postazione='IMP2')
        ct = self.persona('Galli Rino', capoturno=True)
        self.adesso = alle(12, 45)
        pp.controlla()
        self.assertIn('🔔 Linea Incolore', self.notifiche(op))
        self.assertFalse(any('Incolore' in t for t in self.notifiche(ct)))
        p = Pulizia.objects.get(elemento__nome='Linea Incolore')
        self.assertTrue(p.disponibile)
        self.assertEqual(pp.percorso(p), 'PIAZZALE')  # la manda lui al responsabile piazzale

    def test_carrelli_nell_ultimo_turno_della_settimana_del_manutentore(self):
        venerdi = self.persona('Neri Ugo', '2T', 'MANUT', ruolo='', mansione=Mansione.MANUTENTORE, giorno=SABATO - timedelta(days=1))
        man = self.persona('Neri Ugo', '2T', 'MANUT', ruolo='', mansione=Mansione.MANUTENTORE, giorno=SABATO)
        genera_pulizie(venerdi)
        self.assertFalse(venerdi.pulizie.exists())  # non è l'ultimo turno della settimana
        self.adesso = alle(21, 29, SABATO)
        pp.controlla()
        self.assertFalse(self.notifiche(man))
        self.adesso = alle(21, 30, SABATO)
        pp.controlla()
        self.assertIn('🔔 Ingrassaggio e Pulizia Carrelli Elevatori', self.notifiche(man))
        self.assertIn("Mancano 30 min alla fine del turno: completa l'ingrassaggio e la pulizia.", self.messaggi(man))

    def test_voci_dal_file_delle_regole(self):
        e = ElementoPulizia.objects.get(nome='Macchine ottiche - metà turno')
        self.assertEqual((e.avviso, e.avviso_minuti, e.avviso_a, e.con_avvio, e.da_meta), ('DMETA', 15, 'CT', True, True))
        self.assertEqual(ElementoPulizia.objects.get(nome='Pozzetti').avviso, 'INIZIO')
        self.assertEqual(ElementoPulizia.objects.get(nome='Linea Incolore').minuti_prima_fine, 75)
        self.assertEqual(ElementoPulizia.objects.get(nome='Generiche Superbi').convalida, 'PIAZZALE')
        self.assertEqual(ElementoPulizia.objects.filter(attivo=True).count(), 16)
        self.assertFalse(ElementoPulizia.objects.get(nome='Pulizia generale Impianto 2').attivo)

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
        # «Conferma» dalla notifica porta alla pagina dove il RP sceglie a chi assegnarla
        r = self.client.get(reverse('turni:notifica_scelta', args=['straordinaria', s.pk, 'conferma']))
        self.assertRedirects(r, reverse('turni:richiesta_rp', args=[s.pk]), fetch_redirect_response=False)
        self.assertContains(self.client.get(reverse('turni:richiesta_rp', args=[s.pk])), 'Galli Rino')
        self.client.post(reverse('turni:richiesta_rp', args=[s.pk]), {'azione': 'approva', 'turno': ct.pk})
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


@override_settings(PUSH_SINCRONO=True)
class FileRegolePulizieTest(TestCase):
    """Le regole nuove del file «Regole Pulizie - unico.xlsx» (21/11/2026)."""

    setUp = PianoPulizieTest.setUp
    persona = PianoPulizieTest.persona
    entra = PianoPulizieTest.entra
    notifiche = PianoPulizieTest.notifiche

    def rp(self):
        rp = Dipendente.objects.create(nome='Lombardo Gabri', resp_piazzale=True)
        rp.utente = get_user_model().objects.create_user('rp', password='123456')
        rp.save()
        return rp

    def test_avviso_ripetuto_ogni_15_minuti_finche_nessuno_risponde(self):
        op = self.persona('Costa Dino', postazione='IMP2')
        self.adesso = alle(12, 45)
        self.assertEqual(pp.controlla(), 1)
        self.adesso = alle(12, 50)
        self.assertEqual(pp.controlla(), 0)
        self.adesso = alle(13, 0)
        self.assertEqual(pp.controlla(), 1)  # 15 minuti dopo, ancora da fare: si ripete
        self.assertEqual(Notifica.objects.filter(utente=op.dipendente.utente, titolo='🔔 Linea Incolore').count(), 2)
        # fatta: niente più ripetizioni
        Pulizia.objects.filter(elemento__nome='Linea Incolore').update(stato=Pulizia.Stato.FATTA)
        self.adesso = alle(13, 15)
        self.assertEqual(pp.controlla(), 0)

    def test_ricordamelo_poi_torna_identico(self):
        op = self.persona('Costa Dino', postazione='IMP2')
        self.adesso = alle(12, 45)
        pp.controlla()
        p = Pulizia.objects.get(elemento__nome='Linea Incolore')
        self.entra(op)
        self.client.post(reverse('turni:avviso_pulizia', args=[p.pk]), {'minuti': '30'})
        self.adesso = alle(13, 5)
        self.assertEqual(pp.controlla(), 0)  # rimandato: niente ripetizione a 15 minuti
        self.adesso = alle(12, 45) + timedelta(minutes=30, seconds=5)
        self.assertEqual(pp.controlla(), 1)
        self.assertEqual(Notifica.objects.filter(utente=op.dipendente.utente, titolo='🔔 Linea Incolore').count(), 2)

    def test_fine_turno_non_eseguita_avvisa_capi_turno_e_rp(self):
        rp = self.rp()
        self.persona('Costa Dino', postazione='SUPERBI')
        self.adesso = alle(13, 45)
        pp.controlla()
        p = Pulizia.objects.get(elemento__nome='Generiche Superbi')
        self.adesso = alle(14, 1)
        pp.controlla()
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.NON_ESEGUITA)
        self.assertEqual(pp.stato_di(p), 'nonfatta')
        self.assertTrue(Notifica.objects.filter(utente=rp.utente, titolo__contains='non eseguita').exists())
        self.entra(rp)
        self.assertContains(self.client.get(reverse('turni:pulizia_voce', args=[p.pk])), 'Non eseguita')

    def test_pala_settimanale_solo_nell_ultimo_turno_del_palista(self):
        lun = self.persona('Ferri Elio', '1T', 'PALISTA', ruolo='Pal')
        gio = self.persona('Ferri Elio', '1T', 'PALISTA', ruolo='Pal', giorno=LUNEDI + timedelta(days=3))
        genera_pulizie(lun)
        genera_pulizie(gio)
        self.assertNotIn('Pulizia Settimanale Pala', list(lun.pulizie.values_list('elemento__nome', flat=True)))
        self.assertIn('Pulizia Settimanale Pala', list(gio.pulizie.values_list('elemento__nome', flat=True)))
        self.assertIn('Piazzale', list(lun.pulizie.values_list('elemento__nome', flat=True)))

    def test_piu_foto_e_video_con_la_nota(self):
        op = self.persona('Costa Dino', postazione='SUPERBI')
        genera_pulizie(op)
        p = op.pulizie.get(elemento__nome='Generiche Superbi')
        self.adesso = alle(13, 40)
        self.entra(op)
        video = SimpleUploadedFile('v.mp4', b'\x00\x00\x00\x18ftypmp42', content_type='video/mp4')
        self.client.post(reverse('turni:pulizie_turno', args=[op.pk]), {
            'azione': 'fatta', 'pulizia': p.pk, 'foto_prima': [foto(), foto()], 'foto': [foto(), video], 'nota': 'Tutto pulito'})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.FATTA)
        self.assertEqual(p.nota, 'Tutto pulito')
        self.assertTrue(p.foto_prima and p.foto)
        self.assertEqual(p.allegati.count(), 2)  # la seconda foto prima e il video
        a = p.allegati.get(video=True)
        r = self.client.get(reverse('turni:allegato_pulizia', args=[a.pk]))
        self.assertEqual(r['Content-Type'], 'video/mp4')
        # a pezzi, come lo chiede l'iPhone
        r = self.client.get(reverse('turni:allegato_pulizia', args=[a.pk]), HTTP_RANGE='bytes=0-3')
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r.content, b'\x00\x00\x00\x18')
        self.assertTrue(r['Content-Range'].startswith('bytes 0-3/'))
        # dalla scheda il video si apre nella pagina con Indietro
        self.assertContains(self.client.get(reverse('turni:pulizia_voce', args=[p.pk])), 'data-video="1"')
        r = self.client.get(reverse('turni:vedi') + f'?u=/turni/foto/allegato/{a.pk}/&tipo=video', HTTP_REFERER='http://testserver/turni/pulizie/')
        self.assertContains(r, '<video')
        self.assertContains(r, 'Indietro')

    def test_non_si_puo_fare_vuole_nota_e_foto_e_avvisa_capi_turno_e_rp(self):
        rp = self.rp()
        op = self.persona('Costa Dino', postazione='SUPERBI')
        ct = self.persona('Galli Rino', capoturno=True)
        genera_pulizie(op)
        p = op.pulizie.get(elemento__nome='Generiche Superbi')
        self.entra(op)
        url = reverse('turni:pulizie_turno', args=[op.pk])
        self.client.post(url, {'azione': 'impedita', 'pulizia': p.pk, 'motivo': 'Guasto', 'foto': foto()})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.DA_FARE)  # senza nota non passa
        self.client.post(url, {'azione': 'impedita', 'pulizia': p.pk, 'motivo': 'Guasto', 'foto': foto(), 'nota': 'Nastro rotto'})
        p.refresh_from_db()
        self.assertEqual((p.stato, p.nota), (Pulizia.Stato.IMPEDITA, 'Guasto: Nastro rotto'))
        self.assertTrue(Notifica.objects.filter(utente=rp.utente, titolo__contains='Non eseguibile').exists())
        self.assertTrue(Notifica.objects.filter(utente=ct.dipendente.utente, titolo__contains='Non eseguibile').exists())

    def test_capo_turno_registra_le_notturne_se_il_rp_e_assente(self):
        ct = self.persona('Galli Rino', 'N', capoturno=True)
        self.entra(ct)
        r = self.client.get(reverse('turni:pulizie_turno', args=[ct.pk]))
        self.assertContains(r, 'Registra le Generiche Notturne')
        self.client.post(reverse('turni:pulizie_turno', args=[ct.pk]), {'azione': 'notturne'})
        p = ct.pulizie.get(elemento__nome='Generiche Notturne')
        self.assertEqual(p.richiesta_da, ct.dipendente.utente)
        self.adesso = alle(5, 30, LUNEDI + timedelta(days=1))
        pp.controlla()
        self.assertIn('🔔 Generiche Notturne', self.notifiche(ct))

    def test_rp_assegna_le_notturne_e_da_rifare_avvisa(self):
        rp = self.rp()
        ct = self.persona('Galli Rino', 'N', capoturno=True)
        self.client.force_login(rp.utente)
        self.client.post(reverse('turni:pulizie_piazzale'), {'azione': 'notturne', 'turno': ct.pk})
        p = ct.pulizie.get(elemento__nome='Generiche Notturne')
        self.assertTrue(Notifica.objects.filter(utente=ct.dipendente.utente, titolo='🧹 Generiche Notturne').exists())
        Pulizia.objects.filter(pk=p.pk).update(stato=Pulizia.Stato.FATTA, fatta_il=timezone.now(), ok_capoturno_il=timezone.now())
        self.client.post(reverse('turni:pulizie_piazzale'), {'azione': 'rifare', 'pulizia': p.pk, 'nota': 'Manca il pavimento'})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.SEGNALATA)
        self.assertTrue(Notifica.objects.filter(utente=ct.dipendente.utente, titolo__contains='Da rifare').exists())

    def test_foto_della_pulizia_inviata_nella_chat(self):
        from .models import Chat, MessaggioChat

        op = self.persona('Costa Dino', postazione='SUPERBI')
        estraneo = self.persona('Bianchi Luca', postazione='IMP2')
        genera_pulizie(op)
        p = op.pulizie.get(elemento__nome='Generiche Superbi')
        self.adesso = alle(13, 40)
        self.entra(op)
        self.client.post(reverse('turni:pulizie_turno', args=[op.pk]), {
            'azione': 'fatta', 'pulizia': p.pk, 'foto_prima': foto(), 'foto': foto()})
        chat = Chat.objects.create(nome='Superbi', tutti=True)
        u = reverse('turni:foto', args=[p.pk])
        r = self.client.get(reverse('turni:vedi') + f'?u={u}', HTTP_REFERER='http://testserver/turni/pulizie/')
        self.assertContains(r, 'Invia nella chat')
        r = self.client.get(reverse('turni:vedi_in_chat') + f'?u={u}')
        self.assertContains(r, 'Superbi')
        r = self.client.post(reverse('turni:vedi_in_chat'), {'u': u, 'chat': chat.pk, 'testo': 'Ecco la pulizia'})
        m = MessaggioChat.objects.get(chat=chat)
        self.assertTrue(m.foto)
        self.assertEqual((m.testo, m.autore), ('Ecco la pulizia', op.dipendente.utente))
        self.assertRedirects(r, f"{reverse('turni:messaggi')}?vista=chat&chat={chat.pk}#fondo", fetch_redirect_response=False)
        # chi non può vedere la foto non la può nemmeno mandare
        self.entra(estraneo)
        r = self.client.post(reverse('turni:vedi_in_chat'), {'u': u, 'chat': chat.pk})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(MessaggioChat.objects.count(), 1)
