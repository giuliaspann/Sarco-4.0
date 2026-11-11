from datetime import date, datetime, timedelta
from io import BytesIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import Dipendente, ElementoPulizia, Pulizia, PuliziaGenerale, Settimana, Turno
from .pulizie import genera_pulizie, pulizia_generale_in_attesa

GIORNO = date(2026, 11, 2)  # lunedì


def foto():
    b = BytesIO()
    Image.new('RGB', (20, 20), 'red').save(b, 'JPEG')
    return SimpleUploadedFile('f.jpg', b.getvalue(), content_type='image/jpeg')


def alle(ore, minuti=0, giorno=GIORNO):
    return timezone.make_aware(datetime.combine(giorno, datetime.min.time()) + timedelta(hours=ore, minutes=minuti))


class PulizieTurnoTest(TestCase):
    """Le pulizie dal foglio del 30/10: per turno e postazione, controlli, piazzale, notte e Impianto 2."""

    def setUp(self):
        self.sett = Settimana.objects.create(lunedi=GIORNO)
        self.adesso = alle(12)
        patcher = mock.patch('django.utils.timezone.now', side_effect=lambda: self.adesso)
        patcher.start()
        self.addCleanup(patcher.stop)

    def persona(self, nome, fascia, postazione, capoturno=False, ruolo='', **campi):
        d = Dipendente.objects.create(nome=nome, **campi)
        d.utente = get_user_model().objects.create_user(nome.lower(), password='123456')
        d.save()
        return Turno.objects.create(settimana=self.sett, dipendente=d, data=GIORNO, fascia=fascia, postazione=postazione,
                                    capoturno=capoturno, ruolo=ruolo or ('CT' if capoturno else ''))

    def voci(self, turno):
        genera_pulizie(turno)
        return sorted(turno.pulizie.values_list('elemento__nome', flat=True))

    def entra(self, turno):
        self.client.login(username=turno.dipendente.nome.lower(), password='123456')

    def test_pulizie_standard_per_turno_postazione_e_ruolo(self):
        """Il foglio "Regole Pulizie per Area e Ruolo"."""
        # regole dell'11/11: le ottiche le fanno due operatori (qui da soli in turno, quindi tocca a loro)
        self.assertEqual(self.voci(self.persona('A', '1T', 'IMP1', ruolo='OdL')), ['Macchine ottiche', 'Pozzetti'])
        self.assertEqual(self.voci(self.persona('B', '2T', 'IMP1', ruolo='OdL')), ['Macchine ottiche'])
        self.assertEqual(self.voci(self.persona('CT', '1T', 'IMP1', capoturno=True)), [])
        self.assertEqual(self.voci(self.persona('MAN1', '2T', 'IMP1', ruolo='Man')), ['Generiche Manutenzione'])
        self.assertEqual(self.voci(self.persona('C', 'N', 'IMP2', ruolo='OdL')), ['Incolore'])
        self.assertEqual(self.voci(self.persona('D', '2T', 'BARROTTI', ruolo='OdL')), ['Barrotti'])
        self.assertEqual(self.voci(self.persona('E', '1T', 'PALISTA', ruolo='Pal')), ['Pala', 'Piazzale + corridoio granella'])
        self.assertEqual(self.voci(self.persona('E2', '1T', 'IMP1', ruolo='Pal')), ['Pala', 'Piazzale + corridoio granella'])
        self.assertEqual(self.voci(self.persona('F', '2T', 'PALISTA', ruolo='Pal')), ['Pala'])
        self.assertEqual(self.voci(self.persona('G', 'G', 'MULINO', ruolo='OdL')), ['Mulino e pressa'])
        # di notte le generiche le assegna il responsabile; le ottiche le fanno due operatori di turno
        self.assertEqual(self.voci(self.persona('I', 'N', 'IMP1', ruolo='OdL')), ['Macchine ottiche'])

    def test_capo_turno_e_palista_ha_le_pulizie_di_tutti_e_due(self):
        crimi = self.persona('CRIMI', 'N', 'IMP1', capoturno=True)
        crimi.incarichi = 'IMP1/CT IMP1/Pal'
        crimi.save()
        self.assertEqual(self.voci(crimi), [])  # il Capo Turno non fa pulizie, supervisiona (regola dell'11/11)
        # chi è palista all'impianto e operatore alla sabbia non prende le pulizie degli operatori dell'impianto
        titone = self.persona('TITONE', '2T', 'IMP1', ruolo='Pal')
        titone.incarichi = 'IMP1/Pal SABBIA/OdL'
        titone.save()
        self.assertEqual(self.voci(titone), ['Pala'])

    def test_prima_il_capo_turno_poi_il_responsabile_piazzale(self):
        op = self.persona('OP', '1T', 'IMP1', ruolo='OdL')
        capo = self.persona('CAPO', '1T', 'IMP1', capoturno=True)
        resp = self.persona('LOMBARDO GABRIELE', 'G', 'UFFICIO', resp_piazzale=True)
        genera_pulizie(op)
        p = op.pulizie.get(elemento__nome='Macchine ottiche')
        self.adesso = alle(13, 40)
        self.entra(op)
        self.client.post(reverse('turni:pulizie_turno', args=[op.pk]), {'azione': 'fatta', 'pulizia': p.pk})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.FATTA)

        self.entra(resp)  # prima dell'ok del Capo Turno il responsabile non la vede
        self.assertNotIn(p, self.client.get(reverse('turni:pulizie_piazzale')).context['da_convalidare'])

        self.entra(capo)
        self.client.post(reverse('turni:capoturno') + f'?giorno={GIORNO}', {'azione': 'verifica', 'pulizia': p.pk})
        p.refresh_from_db()
        self.assertEqual((p.stato, p.ok_capoturno_da), (Pulizia.Stato.FATTA, capo.dipendente.utente))
        self.assertContains(self.client.get(reverse('turni:capoturno') + f'?giorno={GIORNO}'), 'Dal responsabile piazzale')

        self.entra(resp)
        r = self.client.get(reverse('turni:pulizie_piazzale'))
        self.assertContains(r, 'Macchine ottiche')
        self.assertContains(r, 'ok di Capo')
        self.client.post(reverse('turni:pulizie_piazzale'), {'azione': 'convalida', 'pulizia': p.pk})
        p.refresh_from_db()
        self.assertEqual((p.stato, p.verificata_da), (Pulizia.Stato.VERIFICATA, resp.dipendente.utente))

    def test_il_capo_turno_vede_e_verifica_solo_il_suo_turno(self):
        mattina = self.persona('OP1', '1T', 'IMP1', ruolo='OdL')
        sera = self.persona('OP2', '2T', 'IMP1', ruolo='OdL')
        capo = self.persona('CAPO', '1T', 'IMP1', capoturno=True)
        for t in (mattina, sera):
            genera_pulizie(t)
        p_sera = sera.pulizie.get(elemento__nome='Macchine ottiche')  # da solo in turno: le ottiche toccano a lui
        p_sera.stato = Pulizia.Stato.FATTA
        p_sera.save()
        self.entra(capo)
        r = self.client.get(reverse('turni:capoturno') + f'?giorno={GIORNO}')
        self.assertEqual([t.dipendente.nome for t in r.context['turni']], ['OP1'])
        self.client.post(reverse('turni:capoturno') + f'?giorno={GIORNO}', {'azione': 'verifica', 'pulizia': p_sera.pk})
        p_sera.refresh_from_db()
        self.assertIsNone(p_sera.ok_capoturno_il)  # non è del suo turno

    def test_pozzetti_a_turno_tra_gli_operatori(self):
        operatori = [self.persona(n, '1T', 'IMP1', ruolo='OdL') for n in ('P1', 'P2', 'P3')]
        con_pozzetti = [t for t in operatori if 'Pozzetti' in self.voci(t)]
        self.assertEqual(len(con_pozzetti), 1)
        # il giorno dopo tocca a un altro
        domani = [Turno.objects.create(settimana=self.sett, dipendente=t.dipendente, data=GIORNO + timedelta(days=1),
                                       fascia='1T', postazione='IMP1', ruolo='OdL') for t in operatori]
        con_pozzetti_domani = [t for t in domani if 'Pozzetti' in self.voci(t)]
        self.assertEqual(len(con_pozzetti_domani), 1)
        self.assertNotEqual(con_pozzetti[0].dipendente, con_pozzetti_domani[0].dipendente)

    def test_linea_incolore_un_ora_prima_della_fine_con_foto(self):
        t = self.persona('A', '1T', 'IMP2')
        genera_pulizie(t)
        p = t.pulizie.get(elemento__nome='Incolore')
        self.entra(t)
        url = reverse('turni:pulizie_turno', args=[t.pk])
        self.assertContains(self.client.get(reverse('turni:pulizie')), 'Dalle 13:00')
        self.client.post(url, {'azione': 'fatta', 'pulizia': p.pk, 'foto_prima': foto(), 'foto': foto()})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.DA_FARE)  # alle 12 è troppo presto
        self.adesso = alle(13, 5)
        self.client.post(url, {'azione': 'fatta', 'pulizia': p.pk, 'foto': foto()})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.DA_FARE)  # manca la foto prima
        self.client.post(url, {'azione': 'fatta', 'pulizia': p.pk, 'foto_prima': foto(), 'foto': foto()})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.FATTA)

    def test_foto_dopo_e_solo_tasto_vanno_al_responsabile_piazzale(self):
        barrotti = self.persona('A', '1T', 'BARROTTI')
        mulino = self.persona('B', 'G', 'MULINO')
        for t in (barrotti, mulino):
            genera_pulizie(t)
        self.adesso = alle(13, 40)
        self.entra(barrotti)
        p = barrotti.pulizie.get()
        r = self.client.get(reverse('turni:pulizie_turno', args=[barrotti.pk]) + f'?fai=assegnata&voce={p.pk}')
        self.assertContains(r, 'Foto dopo')
        self.assertNotContains(r, 'Foto prima')
        self.client.post(reverse('turni:pulizie_turno', args=[barrotti.pk]), {'azione': 'fatta', 'pulizia': p.pk})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.DA_FARE)  # serve la foto dopo
        self.client.post(reverse('turni:pulizie_turno', args=[barrotti.pk]), {'azione': 'fatta', 'pulizia': p.pk, 'foto': foto()})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.FATTA)  # la convalida il responsabile piazzale

        self.adesso = alle(17, 10)
        self.entra(mulino)
        p = mulino.pulizie.get()
        r = self.client.get(reverse('turni:pulizie_turno', args=[mulino.pk]) + f'?fai=assegnata&voce={p.pk}')
        self.assertNotContains(r, 'Foto dopo')  # solo tasto
        self.client.post(reverse('turni:pulizie_turno', args=[mulino.pk]), {'azione': 'fatta', 'pulizia': p.pk})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.FATTA)

    def test_piazzale_pulito_lo_convalida_il_responsabile(self):
        palista = self.persona('PALISTA', '1T', 'PALISTA')
        capo = self.persona('CAPO', '1T', 'IMP1', capoturno=True)
        resp = self.persona('LOMBARDO GABRIELE', 'G', 'UFFICIO', resp_piazzale=True)
        genera_pulizie(palista)
        p = palista.pulizie.get(elemento__nome='Piazzale + corridoio granella')
        self.entra(palista)
        r = self.client.get(reverse('turni:pulizie_turno', args=[palista.pk]) + f'?fai=assegnata&voce={p.pk}')
        self.assertContains(r, 'Piazzale pulito')
        self.client.post(reverse('turni:pulizie_turno', args=[palista.pk]), {'azione': 'fatta', 'pulizia': p.pk})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.FATTA)

        self.entra(capo)  # il Capo Turno non lo convalida
        self.client.post(reverse('turni:capoturno') + f'?giorno={GIORNO}', {'azione': 'verifica', 'pulizia': p.pk})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.FATTA)

        self.entra(resp)
        self.assertContains(self.client.get(reverse('turni:pulizie_piazzale')), 'Pulizie da convalidare')
        self.client.post(reverse('turni:pulizie_piazzale'), {'azione': 'convalida', 'pulizia': p.pk})
        p.refresh_from_db()
        self.assertEqual((p.stato, p.verificata_da), (Pulizia.Stato.VERIFICATA, resp.dipendente.utente))

    def test_notte_responsabile_ai_capi_turno_poi_agli_operatori(self):
        resp = self.persona('LOMBARDO GABRIELE', 'G', 'UFFICIO', resp_piazzale=True)
        capo = self.persona('CAPO', 'N', 'IMP1', capoturno=True)
        op = self.persona('OPERAIO', 'N', 'IMP1')
        self.adesso = alle(17, 30)
        self.entra(resp)
        r = self.client.get(reverse('turni:pulizie_piazzale'))
        self.assertTrue(r.context['in_ritardo'])  # dopo le 17 senza assegnazioni
        self.client.post(reverse('turni:pulizie'), {'azione': 'richiedi', 'torna': 'piazzale', 'turno': capo.pk, 'nota': 'Zona carico'})
        p = capo.pulizie.get(nota='Zona carico')
        self.assertFalse(self.client.get(reverse('turni:pulizie_piazzale')).context['in_ritardo'])

        self.entra(capo)
        r = self.client.get(reverse('turni:pulizie_turno', args=[capo.pk]) + f'?fai=assegnata&voce={p.pk}')
        self.assertContains(r, 'Passa la pulizia')
        self.client.post(reverse('turni:pulizie_turno', args=[capo.pk]), {'azione': 'passa', 'pulizia': p.pk, 'a': op.pk})
        p.refresh_from_db()
        self.assertEqual((p.turno, p.richiesta_da), (op, capo.dipendente.utente))
        self.assertIn('Lombardo', p.nota)

    def test_pulizia_generale_impianto_2_ogni_due_settimane(self):
        resp = self.persona('LOMBARDO GABRIELE', 'G', 'UFFICIO', resp_piazzale=True)
        self.entra(resp)
        self.assertContains(self.client.get(reverse('turni:pulizie_piazzale')), 'Pulizia generale Impianto 2')
        self.client.post(reverse('turni:pulizie_piazzale'), {'azione': 'generale_no'})
        self.assertEqual(PuliziaGenerale.objects.get().esito, PuliziaGenerale.Esito.NON_NECESSARIA)
        self.assertIsNone(pulizia_generale_in_attesa())  # fino a tra 2 settimane non chiede più
        self.adesso = alle(9, giorno=GIORNO + timedelta(days=14))
        r = self.client.post(reverse('turni:pulizie_piazzale'), {'azione': 'generale_si'})
        self.assertIn('area=IMP2', r['Location'])
        self.assertEqual(PuliziaGenerale.objects.first().esito, PuliziaGenerale.Esito.DA_FARE)
        self.assertEqual(PuliziaGenerale.objects.count(), 2)

    def test_voci_create_dalla_migrazione(self):
        e = ElementoPulizia.objects.get(nome='Piazzale + corridoio granella')  # era "Piazzale": rinominata
        self.assertEqual((e.modo, e.convalida, e.tasto), ('SOLO_TASTO', 'PIAZZALE', 'Piazzale pulito'))
        e = ElementoPulizia.objects.get(nome='Pavimentazione + altro')
        self.assertEqual((e.modo, e.convalida, e.minuti_prima_fine), ('SOLO_TASTO', 'CT_RP', 30))
        self.assertEqual(sorted(e.regole.values_list('fascia', 'ruolo')), [('1T', 'OdL'), ('2T', 'OdL')])
    def test_controllo_vagli_zig_zag_mercoledi_e_sabato(self):
        from .models import Intervento
        from .pulizie import promemoria_di

        t = self.persona('A', '1T', 'IMP1')
        self.assertEqual(promemoria_di(t), [])  # lunedì no
        mer = GIORNO + timedelta(days=2)
        op = Turno.objects.create(settimana=self.sett, dipendente=t.dipendente, data=mer, fascia='1T', postazione='IMP1')
        altro = Turno.objects.create(settimana=self.sett, dipendente=self.persona('B', 'RIP', '').dipendente, data=mer,
                                     fascia='1T', postazione='IMP1')
        capo = Turno.objects.create(settimana=self.sett, dipendente=self.persona('CAPO', 'RIP', '').dipendente, data=mer,
                                    fascia='1T', postazione='IMP1', capoturno=True)
        sabato_sera = Turno.objects.create(settimana=self.sett, dipendente=t.dipendente, data=GIORNO + timedelta(days=5),
                                           fascia='2T', postazione='IMP1')
        self.assertEqual(promemoria_di(op)[0]['ora'].strftime('%H:%M'), '13:00')
        self.assertEqual(promemoria_di(sabato_sera)[0]['ora'].strftime('%H:%M'), '21:00')
        self.assertNotIn('Controllo vagli zig-zag', self.voci(op))  # non si crea da solo: lo assegna il Capo Turno

        self.adesso = alle(12, 30, giorno=mer)
        self.entra(altro)  # avviso per tutti quelli dell'Impianto 1, senza tasto
        r = self.client.get(reverse('turni:oggi'))
        self.assertContains(r, 'Fermo produzione')
        self.assertNotContains(r, 'Fai il controllo')
        self.entra(capo)
        self.assertContains(self.client.get(reverse('turni:oggi')), 'Assegna il controllo')
        e = ElementoPulizia.objects.get(nome='Controllo vagli zig-zag')
        self.client.post(reverse('turni:pulizie'), {'azione': 'richiedi', 'squadra': '1', 'controllo': e.pk, 'turno': op.pk})
        p = op.pulizie.get(elemento=e)
        self.assertNotContains(self.client.get(reverse('turni:oggi')), 'Assegna il controllo')

        self.entra(op)
        self.assertContains(self.client.get(reverse('turni:oggi')), 'Fai il controllo')
        self.adesso = alle(13, 10, giorno=mer)
        url = reverse('turni:pulizie_turno', args=[op.pk])
        self.client.post(url, {'azione': 'fatta', 'pulizia': p.pk, 'da': 'oggi'})
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.FATTA)  # tutto ok: lo convalida il Capo Turno
        self.entra(capo)
        self.assertContains(self.client.get(reverse('turni:capoturno') + f'?giorno={mer}'), 'fermo produzione')
        self.client.post(reverse('turni:capoturno') + f'?giorno={mer}', {'azione': 'verifica', 'pulizia': p.pk})
        p.refresh_from_db()
        # ok del Capo Turno; poi lo convalida il responsabile piazzale
        self.assertEqual((p.stato, p.ok_capoturno_da), (Pulizia.Stato.FATTA, capo.dipendente.utente))

        # il sabato c'è un problema: diventa un guasto dei vagli, con la foto
        p2 = Pulizia.objects.create(turno=sabato_sera, elemento=e, richiesta_da=capo.dipendente.utente)
        self.adesso = alle(21, 5, giorno=sabato_sera.data)
        self.entra(op)
        url = reverse('turni:pulizie_turno', args=[sabato_sera.pk])
        vagli = Intervento.objects.filter(macchina__codice='IMP1-ZIGZAG')
        self.client.post(url, {'azione': 'problema', 'pulizia': p2.pk, 'nota': 'Rete rotta'})
        self.assertFalse(vagli.exists())  # senza foto non parte
        self.client.post(url, {'azione': 'problema', 'pulizia': p2.pk, 'nota': 'Rete rotta', 'foto': foto()})
        self.assertEqual(vagli.get().descrizione, 'Controllo vagli zig-zag: Rete rotta')
        p2.refresh_from_db()
        self.assertEqual(p2.stato, Pulizia.Stato.IMPEDITA)

    def test_vagli_al_manutentore_di_turno(self):
        from .pulizie import promemoria_di

        mer = GIORNO + timedelta(days=2)
        crea = lambda nome, post, capo=False, **c: Turno.objects.create(  # noqa: E731
            settimana=self.sett, dipendente=self.persona(nome, 'RIP', '', **c).dipendente, data=mer, fascia='1T',
            postazione=post, capoturno=capo)
        op = crea('LINEA', 'IMP1')
        capo = crea('CAPO', 'IMP1', capo=True)
        mt = crea('MANUTENTORE', 'MANUT', mansione='MANUTENTORE')
        self.adesso = alle(12, giorno=mer)
        c = promemoria_di(op)[0]['controllo']
        self.assertEqual(c.turno, mt)  # va da solo al manutentore di turno
        self.assertEqual(promemoria_di(mt)[0]['controllo'], c)  # lui vede l'avviso anche se non è all'Impianto 1
        self.entra(mt)
        self.assertContains(self.client.get(reverse('turni:oggi')), 'Fai il controllo')

        self.entra(capo)  # niente da assegnare: c'è il manutentore
        self.assertNotContains(self.client.get(reverse('turni:oggi')), 'Assegna il controllo')


class TurniProvaCapoTest(TestCase):
    def test_dipendente_di_prova_capo_turno_tutti_i_giorni(self):
        uff = get_user_model().objects.create_user('uff', is_staff=True)
        dip = Dipendente.objects.create(nome='PROVA CAPOTURNO')
        self.client.force_login(uff)
        self.client.post(reverse('turni:dipendenti'), {'dipendente': dip.pk, 'azione': 'turni_prova_capo'})
        turni = dip.turni.all()
        self.assertEqual(turni.count(), 14)
        self.assertTrue(all(t.capoturno and t.fascia == '1T' and t.postazione == 'IMP1' for t in turni))
