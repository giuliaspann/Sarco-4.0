from datetime import datetime, time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from . import importa
from . import richieste as svc
from .models import CambioTurno, Dipendente, Fascia, Postazione, RichiestaFerie, Turno
from .tests import LUNEDI, RIGHE, file_turni


class RichiesteTest(TestCase):
    """Spano e Drame si scambiano martedì (Spano riposa, Drame 2T Imp. 2) con mercoledì
    (Spano Capo Turno, Drame riposa). "Oggi" è lunedì 12/10 alle 8."""

    MAR, MER = LUNEDI + timedelta(days=1), LUNEDI + timedelta(days=2)

    def setUp(self):
        importa.salva_settimana(importa.leggi_file(file_turni(RIGHE), LUNEDI))
        User = get_user_model()
        for nome, user in [("SPANO' A. MAURO", 'spano'), ('DRAME BOUBA', 'drame'), ('CRIMI BENITO', 'crimi')]:
            d = Dipendente.objects.get(nome=nome)
            d.utente = User.objects.create_user(user, password='123456')
            d.save()
        self.spano = Dipendente.objects.get(nome="SPANO' A. MAURO")
        self.drame = Dipendente.objects.get(nome='DRAME BOUBA')
        self.resp = User.objects.create_user('resp', password='x')
        self.resp.user_permissions.add(Permission.objects.get(codename='approva_richieste'))
        adesso = timezone.make_aware(datetime.combine(LUNEDI, datetime.min.time()) + timedelta(hours=8))
        patcher = mock.patch('django.utils.timezone.now', return_value=adesso)
        patcher.start()
        self.addCleanup(patcher.stop)

    def turno(self, dip, giorno):
        return Turno.objects.get(dipendente=dip, data=giorno)

    def chiedi(self):
        self.client.login(username='spano', password='123456')
        r = self.client.post(
            reverse('turni:nuovo_cambio'),
            {'giorno': self.MAR, 'collega': self.drame.pk, 'giorno2': self.MER, 'motivo': 'visita medica'},
        )
        self.assertRedirects(r, reverse('turni:richieste'), fetch_redirect_response=False)
        return CambioTurno.objects.get()

    def test_percorso_completo(self):
        # il giorno di recupero non si propone più (chiesto di toglierlo)
        self.client.login(username='spano', password='123456')
        r = self.client.get(reverse('turni:nuovo_cambio'), {'giorno': self.MAR, 'collega': self.drame.pk})
        self.assertNotContains(r, 'Giorno di recupero')

        cambio = self.chiedi()
        self.assertEqual(cambio.stato, CambioTurno.Stato.ATTESA_COLLEGA)

        # l'ufficio non può approvare prima del collega
        self.client.login(username='resp', password='x')
        self.client.post(reverse('turni:ufficio_richieste'), {'cambio': cambio.pk, 'azione': 'approva'})
        cambio.refresh_from_db()
        self.assertEqual(cambio.stato, CambioTurno.Stato.ATTESA_COLLEGA)

        # un altro collega non può rispondere al posto di Drame
        self.client.login(username='crimi', password='123456')
        r = self.client.post(reverse('turni:richieste'), {'cambio': cambio.pk, 'azione': 'accetta'})
        self.assertEqual(r.status_code, 404)

        self.client.login(username='drame', password='123456')
        self.assertContains(self.client.get(reverse('turni:richieste'), follow=True), 'ti chiede un cambio')
        self.client.post(reverse('turni:richieste'), {'cambio': cambio.pk, 'azione': 'accetta'})
        cambio.refresh_from_db()
        self.assertEqual(cambio.stato, CambioTurno.Stato.ATTESA_UFFICIO)
        self.assertEqual(self.turno(self.spano, self.MAR).fascia, Fascia.RIPOSO)  # non ancora applicato

        self.client.login(username='resp', password='x')
        self.assertContains(self.client.get(reverse('turni:ufficio_richieste')), 'visita medica')
        self.client.post(reverse('turni:ufficio_richieste'), {'cambio': cambio.pk, 'azione': 'approva'})
        cambio.refresh_from_db()
        self.assertEqual(cambio.stato, CambioTurno.Stato.APPROVATO)

        mar_s, mer_s = self.turno(self.spano, self.MAR), self.turno(self.spano, self.MER)
        mar_d, mer_d = self.turno(self.drame, self.MAR), self.turno(self.drame, self.MER)
        self.assertEqual((mar_s.fascia, mar_s.postazione), (Fascia.POMERIGGIO, Postazione.IMP2))
        self.assertEqual(mar_d.fascia, Fascia.RIPOSO)
        self.assertEqual(mer_s.fascia, Fascia.RIPOSO)
        self.assertTrue(mer_d.capoturno)
        self.assertIn('Drame', mar_s.nota_modifica)

        # ricaricando lo stesso Excel il cambio resta e l'ufficio viene avvisato
        _, _, mantenuti = importa.salva_settimana(importa.leggi_file(file_turni(RIGHE), LUNEDI))
        self.assertEqual(len(mantenuti), 4)
        self.assertEqual(self.turno(self.spano, self.MAR).fascia, Fascia.POMERIGGIO)

    def test_turni_cambiati_nel_frattempo(self):
        cambio = self.chiedi()
        svc.risposta_collega(cambio, True)
        corrette = [list(r) for r in RIGHE]
        corrette[1][2] = '1T- Imp. 1 '  # martedì di Drame corretto nel file
        importa.salva_settimana(importa.leggi_file(file_turni(corrette), LUNEDI))
        with self.assertRaises(svc.RichiestaNonValida):
            svc.decisione_ufficio_cambio(cambio, self.resp, True)
        self.assertEqual(self.turno(self.spano, self.MAR).fascia, Fascia.RIPOSO)

    def test_controlli_richiesta(self):
        with self.assertRaises(svc.RichiestaNonValida):  # oggi non si cambia
            svc.crea_cambio(self.spano, self.drame, LUNEDI)
        with self.assertRaises(svc.RichiestaNonValida):  # giovedì hanno lo stesso turno
            svc.crea_cambio(self.spano, self.drame, LUNEDI + timedelta(days=3))
        with self.assertRaises(svc.RichiestaNonValida):  # settimana non ancora pubblicata
            svc.crea_cambio(self.spano, self.drame, LUNEDI + timedelta(days=9))
        self.chiedi()
        with self.assertRaises(svc.RichiestaNonValida):  # c'è già una richiesta aperta
            svc.crea_cambio(self.drame, self.spano, self.MAR)

    def test_collega_senza_app_risponde_prima_lui(self):
        self.drame.utente = None
        self.drame.save()
        self.client.login(username='spano', password='123456')
        r = self.client.get(reverse('turni:nuovo_cambio'), {'giorno': self.MAR, 'collega': self.drame.pk})
        self.assertContains(r, 'cb-invia')
        self.assertEqual(self.chiedi().stato, CambioTurno.Stato.ATTESA_COLLEGA)

    def test_rifiuto_del_collega(self):
        cambio = self.chiedi()
        self.client.login(username='drame', password='123456')
        self.client.post(reverse('turni:richieste'), {'cambio': cambio.pk, 'azione': 'rifiuta'})
        cambio.refresh_from_db()
        self.assertEqual(cambio.stato, CambioTurno.Stato.RIFIUTATO_COLLEGA)

    def test_solo_il_responsabile_approva(self):
        get_user_model().objects.create_user('staff', password='x', is_staff=True)
        self.client.login(username='staff', password='x')
        self.assertEqual(self.client.get(reverse('turni:ufficio_richieste')).status_code, 403)
        self.client.login(username='drame', password='123456')
        self.assertEqual(self.client.get(reverse('turni:ufficio_richieste')).status_code, 403)

    def test_ferie(self):
        self.client.login(username='drame', password='123456')
        # ferie e permessi non si chiedono più dall'app (10/11/2026): la pagina rimanda all'Area personale
        r = self.client.post(
            reverse('turni:nuove_ferie'),
            {'tipo': 'FERIE', 'dal': LUNEDI + timedelta(days=3), 'al': LUNEDI + timedelta(days=8)},
        )
        self.assertRedirects(r, reverse('turni:miei_turni'), fetch_redirect_response=False)
        self.assertFalse(RichiestaFerie.objects.exists())
        # una richiesta vecchia ancora in attesa (da giovedì 15 a martedì 20) l'ufficio la può ancora decidere
        f = RichiestaFerie.objects.create(
            dipendente=self.drame, tipo='FERIE', dal=LUNEDI + timedelta(days=3), al=LUNEDI + timedelta(days=8)
        )

        self.client.login(username='resp', password='x')
        self.assertContains(self.client.get(reverse('turni:ufficio_richieste')), 'non sono ancora nei turni caricati')
        self.client.post(reverse('turni:ufficio_richieste'), {'ferie': f.pk, 'azione': 'approva'})
        f.refresh_from_db()
        self.assertEqual(f.stato, RichiestaFerie.Stato.APPROVATA)
        self.assertEqual(self.turno(self.drame, LUNEDI + timedelta(days=3)).fascia, Fascia.FERIE)
        self.assertEqual(self.turno(self.drame, LUNEDI + timedelta(days=4)).fascia, Fascia.FERIE)

        # la settimana dopo, caricata più tardi, prende le ferie approvate
        lun2 = LUNEDI + timedelta(days=7)
        importa.salva_settimana(importa.leggi_file(file_turni(RIGHE, foglio='Sett.43'), lun2))
        self.assertEqual(self.turno(self.drame, lun2).fascia, Fascia.FERIE)
        self.assertEqual(self.turno(self.drame, lun2 + timedelta(days=1)).fascia, Fascia.FERIE)
        self.assertEqual(self.turno(self.drame, lun2 + timedelta(days=3)).fascia, Fascia.MATTINA)


class OrariEPresaVisioneTest(RichiesteTest):
    """Permesso a ore, orari di ritardo/uscita e presa visione dei turni cambiati dall'ufficio."""

    def test_permesso_a_ore(self):
        self.client.login(username='spano', password='123456')
        # i permessi non si chiedono più dall'app: qui una richiesta vecchia rimasta in attesa
        f = RichiestaFerie.objects.create(dipendente=self.spano, tipo='PERMESSO', dal=self.MER, al=self.MER,
                                          dalle=time(8), alle=time(10, 30))
        self.assertEqual((f.dal, f.al, f.orario), (self.MER, self.MER, 'dalle 8:00 alle 10:30'))
        svc.decisione_ufficio_ferie(f, self.resp, True)
        t = self.turno(self.spano, self.MER)
        self.assertTrue(t.capoturno)  # il turno resta, solo annotato
        self.assertIn('8:00', t.nota_modifica)

    def test_orari_di_ritardo_e_uscita(self):
        from .models import AvvisoAssenza

        self.client.login(username='spano', password='123456')
        self.client.post(reverse('turni:nuovo_avviso'), {'tipo': 'USCITA', 'data': LUNEDI})
        self.assertFalse(AvvisoAssenza.objects.exists())
        self.client.post(reverse('turni:nuovo_avviso'), {'tipo': 'USCITA', 'data': LUNEDI, 'dalle': '11:00'})
        self.client.post(reverse('turni:nuovo_avviso'), {'tipo': 'RITARDO', 'data': LUNEDI, 'alle': '09:30', 'dalle': '05:00'})
        self.assertEqual(sorted(a.orario for a in AvvisoAssenza.objects.all()), ['entra alle 9:30', 'esce alle 11:00'])

    def test_presa_visione(self):
        from .models import ModificaTurno

        corrette = [list(r) for r in RIGHE]
        corrette[0][2] = '2T- Imp. 1 '  # martedì di Spano: da riposo a 2° turno
        self.client.force_login(get_user_model().objects.create_user('uff', password='x', is_staff=True))
        importa.salva_settimana(importa.leggi_file(file_turni(corrette), LUNEDI))
        m = ModificaTurno.objects.get()
        self.assertEqual((m.dipendente, m.data), (self.spano, self.MAR))
        self.client.login(username='spano', password='123456')
        # la presa visione sta in Messaggi, sotto "Da leggere"
        r = self.client.get(reverse('turni:messaggi'))
        self.assertContains(r, 'Il tuo turno è cambiato')
        self.assertContains(r, 'Presa visione')
        self.client.post(reverse('turni:presa_visione'))
        m.refresh_from_db()
        self.assertIsNotNone(m.vista_il)
        self.assertNotContains(self.client.get(reverse('turni:messaggi')), 'Il tuo turno è cambiato')
        # l'ufficio vede chi ha preso visione
        self.client.force_login(get_user_model().objects.get(username='uff'))
        self.assertContains(self.client.get(reverse('turni:importa')), 'Presa visione dei turni cambiati')
        # ricaricare lo stesso file non crea altre richieste
        importa.salva_settimana(importa.leggi_file(file_turni(corrette), LUNEDI))
        self.assertEqual(ModificaTurno.objects.count(), 1)


class AnnullaRichiesteTest(RichiesteTest):
    """«Annulla richiesta» sta nel dettaglio di ogni richiesta, non nell'elenco."""

    def test_annulla_dal_dettaglio(self):
        from .models import AvvisoAssenza

        cambio = self.chiedi()
        self.assertNotContains(self.client.get(reverse('turni:miei_turni')), 'Annulla richiesta')
        r = self.client.get(reverse('turni:richiesta', args=['cambio', cambio.pk]))
        self.assertContains(r, 'Annulla richiesta')
        # il collega che ha accettato può annullare finché l'ufficio non decide
        self.client.login(username='drame', password='123456')
        self.client.post(reverse('turni:richieste'), {'cambio': cambio.pk, 'azione': 'accetta'})
        self.assertContains(self.client.get(reverse('turni:richiesta', args=['cambio', cambio.pk])), 'Annulla richiesta')
        self.client.post(reverse('turni:richieste'), {'cambio': cambio.pk, 'azione': 'annulla_cambio'})
        cambio.refresh_from_db()
        self.assertEqual(cambio.stato, CambioTurno.Stato.ANNULLATO)
        self.assertNotContains(self.client.get(reverse('turni:richiesta', args=['cambio', cambio.pk])), 'Annulla richiesta')

        f = RichiestaFerie.objects.create(dipendente=self.drame, tipo=RichiestaFerie.Tipo.FERIE, dal=self.MER, al=self.MER)
        self.assertContains(self.client.get(reverse('turni:richiesta', args=['ferie', f.pk])), 'Annulla richiesta')
        self.client.post(reverse('turni:richieste'), {'ferie': f.pk, 'azione': 'annulla_ferie'})
        f.refresh_from_db()
        self.assertEqual(f.stato, RichiestaFerie.Stato.ANNULLATA)

        a = AvvisoAssenza.objects.create(dipendente=self.drame, data=self.MAR, tipo=AvvisoAssenza.Tipo.RITARDO)
        self.client.post(reverse('turni:richieste'), {'avviso': a.pk, 'azione': 'annulla_avviso'})
        a.refresh_from_db()
        self.assertIsNotNone(a.annullato_il)
        self.assertContains(self.client.get(reverse('turni:richiesta', args=['avviso', a.pk])), 'Annullato')

        # le richieste degli altri non si aprono
        self.client.login(username='crimi', password='123456')
        self.assertEqual(self.client.get(reverse('turni:richiesta', args=['ferie', f.pk])).status_code, 404)
