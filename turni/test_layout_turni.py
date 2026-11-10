"""Caricamento del file del responsabile turni: foglio "Layout Turni" + "Collegamento Nomi"."""

from datetime import date, datetime, timedelta
from io import BytesIO

import openpyxl
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from . import importa
from .models import Dipendente, Fascia, Postazione, Turno

LUNEDI = date(2026, 11, 9)
GIORNI = ['Lunedì', 'Martedì', 'Mercoledì', 'Giovedì', 'Venerdì', 'Sabato', 'Domenica']

# (area, turno, ruolo, sigla, lun…dom); il turno vuoto continua quello della riga sopra
RIGHE = [
    ('Impianto 1', '1T', 'Capo Turno', 'CT', 'Oddo', 'Oddo', '-', '-', '-', '-', '-'),
    ('Impianto 1', '', 'Operatore di Linea', 'OdL', 'Jarju', 'Jarju', '-', '-', '-', '-', '-'),
    ('Impianto 1', '', 'Palista', 'Pal', 'Titone', 'Titone', '-', '-', '-', '-', '-'),
    ('Impianto 1', '2T', 'Palista', 'Pal', 'Modello', '-', '-', '-', '-', '-', '-'),
    ('Piazzale - Pala', '1T', 'Palista', 'Pal', 'Titone', 'Titone', '-', '-', '-', '-', '-'),
    ('Piazzale - Pala', '2T', 'Palista', 'Pal', 'Modello', '-', '-', '-', '-', '-', '-'),
    ('Sabbia - Sarco', '2T', 'Operatore di Linea', 'OdL', 'Modello', '-', '-', '-', '-', '-', '-'),
    ('Sabbia - Superbi', '1T', 'Operatore di Linea', 'OdL', 'X', '-', '-', '-', '-', '-', '-'),
    ('Piazzale - Rotovaglio', '1T', 'Palista', 'Pal', '-', 'Ignoto', '-', '-', '-', '-', '-'),
]
NOMI = [('Oddo', 'ODDO FEDERICO'), ('Jarju', 'JARJU NABIE'), ('Titone', 'TITONE GIUSEPPE'),
        ('Modello', 'MODELLO FRANCESCO'), ('Rallo', 'RALLO GASPARE'), ('X', '(segnaposto)')]


def file_layout(righe=RIGHE, nomi=NOMI, lunedi=LUNEDI):
    wb = openpyxl.Workbook()
    vista = wb.active
    vista.title = 'Vista Dipendenti'
    vista['B1'] = 'Lunedì della settimana:'
    vista['C1'] = datetime.combine(lunedi, datetime.min.time())
    ws = wb.create_sheet('Layout Turni')
    for i, g in enumerate(GIORNI):
        ws.cell(2, 7 + i, g)
    for c, t in enumerate(['Area', 'Area (Abbr.)', 'Turno', 'Ruolo', 'Ruolo (Abbr.)'], start=2):
        ws.cell(3, c, t)
    for r, (area, turno, ruolo, sigla, *giorni) in enumerate(righe, start=4):
        ws.cell(r, 2, area)
        ws.cell(r, 4, turno or None)
        ws.cell(r, 5, ruolo)
        ws.cell(r, 6, sigla)
        for i, nome in enumerate(giorni):
            ws.cell(r, 7 + i, nome)
    cn = wb.create_sheet('Collegamento Nomi')
    cn['B3'], cn['C3'] = 'Nome nel Layout', 'Nome completo (Elenco Dipendenti)'
    for r, (breve, completo) in enumerate(nomi, start=4):
        cn.cell(r, 2, breve)
        cn.cell(r, 3, completo)
    wb.create_sheet('Calcoli')
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    buf.name = 'Organizzazione_Turni_con_Vista.xlsx'
    return buf


def riga(letta, nome):
    return next(r for r in letta.righe if r.nome == nome)


class LetturaLayoutTest(TestCase):
    def test_lunedi_dalla_vista(self):
        self.assertEqual(importa.lunedi_dal_file(file_layout()), LUNEDI)

    def test_posti_e_nomi_completi(self):
        letta = importa.leggi_file(file_layout(), LUNEDI)
        oddo = riga(letta, 'ODDO FEDERICO').turni[0]
        self.assertEqual((oddo.fascia, oddo.postazione, oddo.capoturno, oddo.ruolo), (Fascia.MATTINA, Postazione.IMP1, True, 'CT'))
        self.assertEqual(oddo.posto, 'Impianto 1 · Capo Turno')
        jarju = riga(letta, 'JARJU NABIE').turni[1]
        self.assertEqual((jarju.fascia, jarju.postazione, jarju.capoturno), (Fascia.MATTINA, Postazione.IMP1, False))
        self.assertEqual(riga(letta, 'JARJU NABIE').turni[2].fascia, Fascia.RIPOSO)

    def test_palista_impianto_non_ripetuto_sulla_pala(self):
        letta = importa.leggi_file(file_layout(), LUNEDI)
        titone = riga(letta, 'TITONE GIUSEPPE').turni[0]
        self.assertEqual((titone.postazione, titone.ruolo), (Postazione.IMP1, 'Pal'))
        self.assertEqual(titone.posto, 'Impianto 1 · Palista')

    def test_due_posti_nello_stesso_turno(self):
        letta = importa.leggi_file(file_layout(), LUNEDI)
        modello = riga(letta, 'MODELLO FRANCESCO').turni[0]
        self.assertEqual(modello.fascia, Fascia.POMERIGGIO)
        self.assertEqual(modello.posto, 'Impianto 1 · Palista + Sabbia - Sarco · Operatore di Linea')
        self.assertEqual(modello.incarichi, 'IMP1/Pal SABBIA/OdL')

    def test_chi_non_e_nel_layout_e_a_riposo_e_segnaposto_saltati(self):
        letta = importa.leggi_file(file_layout(), LUNEDI)
        nomi = [r.nome for r in letta.righe]
        self.assertIn('RALLO GASPARE', nomi)
        self.assertTrue(all(t.fascia == Fascia.RIPOSO for t in riga(letta, 'RALLO GASPARE').turni))
        self.assertNotIn('(SEGNAPOSTO)', nomi)
        self.assertNotIn('X', nomi)
        self.assertTrue(any('X' in a and 'saltate' in a for a in letta.avvisi))
        self.assertTrue(any('Ignoto' in a for a in letta.avvisi))
        ignoto = riga(letta, 'IGNOTO').turni[1]
        self.assertEqual(ignoto.postazione, Postazione.ROTOVAGLIO)

    def test_anteprima_in_sessione_conserva_il_posto(self):
        letta = importa.da_sessione(importa.in_sessione(importa.leggi_file(file_layout(), LUNEDI)))
        self.assertEqual(riga(letta, 'ODDO FEDERICO').turni[0].posto, 'Impianto 1 · Capo Turno')


class CaricamentoLayoutTest(TestCase):
    def setUp(self):
        self.ufficio = get_user_model().objects.create_user('uff', password='x', is_staff=True)
        Dipendente.objects.create(nome='ODDO FEDERICO')

    def test_carica_anteprima_e_pubblica(self):
        self.client.force_login(self.ufficio)
        r = self.client.post(reverse('turni:importa'), {'file': file_layout()})
        self.assertRedirects(r, reverse('turni:anteprima'))
        r = self.client.get(reverse('turni:anteprima'))
        self.assertContains(r, 'Impianto 1 · Capo Turno')
        self.client.post(reverse('turni:anteprima'))
        t = Turno.objects.get(dipendente__nome='ODDO FEDERICO', data=LUNEDI)
        self.assertEqual(t.descrizione, '1° turno · Impianto 1 · Capo Turno')
        self.assertEqual(t.nome_postazione, 'Impianto 1 · Capo Turno')
        self.assertTrue(t.capoturno)
        m = Turno.objects.get(dipendente__nome='MODELLO FRANCESCO', data=LUNEDI)
        self.assertIn('Sabbia - Sarco', m.descrizione)

    def test_ricaricare_aggiorna_senza_doppioni(self):
        importa.salva_settimana(importa.leggi_file(file_layout(), LUNEDI))
        righe = [list(r) for r in RIGHE]
        righe[1][4] = 'Rallo'  # lunedì Jarju sostituito da Rallo
        importa.salva_settimana(importa.leggi_file(file_layout(righe), LUNEDI))
        self.assertEqual(Turno.objects.get(dipendente__nome='JARJU NABIE', data=LUNEDI).fascia, Fascia.RIPOSO)
        self.assertEqual(Turno.objects.get(dipendente__nome='RALLO GASPARE', data=LUNEDI).posto, 'Impianto 1 · Operatore di Linea')
        self.assertEqual(Dipendente.objects.filter(nome__startswith='ODDO').count(), 1)


class AnteprimaTest(TestCase):
    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('uff', password='x', is_staff=True))
        self.client.post(reverse('turni:importa'), {'file': file_layout()})

    def test_per_dipendente_in_ordine_alfabetico_con_le_sigle(self):
        r = self.client.get(reverse('turni:anteprima'))
        nomi = [x['nome'] for x in r.context['righe']]
        self.assertEqual(nomi, sorted(nomi))
        self.assertContains(r, '1T | Impianto 1 | CT')
        self.assertContains(r, '2T | Impianto 1 | Pal + Sabbia - Sarco')
        self.assertContains(r, 'Per Area')

    def test_per_area_come_il_layout(self):
        r = self.client.get(reverse('turni:anteprima') + '?vista=area')
        self.assertEqual(r.context['vista'], 'area')
        self.assertEqual([b['area'] for b in r.context['aree']][:2], ['Impianto 1', 'Piazzale - Pala'])
        self.assertContains(r, 'rowspan="3"')  # 1T dell'Impianto 1 su tre righe


class ProfiloUfficioTest(TestCase):
    def test_il_tasto_profilo_dell_ufficio_apre_la_sua_pagina(self):
        u = get_user_model().objects.create_user('ufficio', password='Segreta.123', is_staff=True)
        self.client.force_login(u)
        r = self.client.get(reverse('turni:home'))
        self.assertContains(r, reverse('turni:profilo'))
        self.assertNotContains(r, '/admin/password_change/')
        r = self.client.get(reverse('turni:profilo'))
        self.assertContains(r, 'Cambia password')
        self.assertContains(r, 'Ufficio')
        self.assertEqual(self.client.get(reverse('turni:password')).status_code, 200)

    def test_chi_ha_turni_va_nell_area_personale(self):
        d = Dipendente.objects.create(nome='ROSSI MARIO')
        d.utente = get_user_model().objects.create_user('rossi')
        d.save()
        self.client.force_login(d.utente)
        self.assertRedirects(self.client.get(reverse('turni:profilo')), reverse('turni:miei_turni'))


class TastoAnalisiTest(TestCase):
    def entra(self, nome, mansione='OPERAIO', postazione='IMP1'):
        from django.utils import timezone

        from .models import Settimana

        d = Dipendente.objects.create(nome=nome, mansione=mansione)
        d.utente = get_user_model().objects.create_user(nome.lower().replace(' ', '.'))
        d.save()
        oggi = timezone.localdate()
        sett, _ = Settimana.objects.get_or_create(lunedi=oggi - timedelta(days=oggi.weekday()))
        Turno.objects.create(settimana=sett, dipendente=d, data=oggi, fascia='1T', postazione=postazione)
        self.client.force_login(d.utente)
        return self.client.get(reverse('turni:oggi'))

    def test_capo_turno_in_impianto_non_vede_analisi(self):
        self.assertNotContains(self.entra('CAPO PROVA'), reverse('turni:analisi_nuova'))

    def test_analista_e_chi_e_in_laboratorio_la_vedono(self):
        self.assertContains(self.entra('GALASSI MARIO', mansione='OPERAIO,ANALISTA'), reverse('turni:analisi_nuova'))
        self.assertContains(self.entra('LAB PROVA', postazione='ANALISI'), reverse('turni:analisi_nuova'))


class CentroNotificheTest(TestCase):
    """Il cuore in alto a destra: avvisi (non i semplici messaggi di chat) e menzioni @Cognome."""

    def setUp(self):
        from .models import Chat

        self.chat = Chat.objects.get(nome='Turni')  # creata dalla migrazione 0012
        self.utenti = {}
        for nome in ('ROSSI MARIO', 'BIANCHI LUCA'):
            d = Dipendente.objects.create(nome=nome)
            d.utente = get_user_model().objects.create_user(nome.split()[0].lower())
            d.save()
            self.chat.membri.add(d.utente)
            self.utenti[nome.split()[0]] = d.utente

    def test_gli_avvisi_vanno_nel_centro_notifiche_e_si_leggono(self):
        from . import push
        from .models import Notifica

        push.invia([self.utenti['ROSSI'].pk], 'Cambio approvato', 'Il tuo cambio del 12/11 è approvato', '/turni/richieste/')
        self.client.force_login(self.utenti['ROSSI'])
        r = self.client.get(reverse('turni:home'))
        self.assertContains(r, reverse('turni:notifiche'))
        r = self.client.get(reverse('turni:notifiche'))
        self.assertContains(r, 'Cambio approvato')
        self.assertFalse(Notifica.objects.filter(utente=self.utenti['ROSSI'], letta_il__isnull=True).exists())

    def test_messaggi_di_chat_no_menzioni_si(self):
        from .models import Notifica

        self.client.force_login(self.utenti['BIANCHI'])
        self.client.post(reverse('turni:messaggi'), {'vista': 'chat', 'chat': self.chat.pk, 'azione': 'chat', 'testo': 'Buongiorno a tutti'})
        self.assertFalse(Notifica.objects.filter(utente=self.utenti['ROSSI']).exists())
        self.client.post(reverse('turni:messaggi'), {'vista': 'chat', 'chat': self.chat.pk, 'azione': 'chat', 'testo': '@Rossi mi passi la pala?'})
        n = Notifica.objects.get(utente=self.utenti['ROSSI'])
        self.assertIn('ti ha menzionato', n.titolo)
        self.assertFalse(Notifica.objects.filter(utente=self.utenti['BIANCHI']).exists())

    def test_barra_logo_al_centro_chat_in_basso_esci_nel_profilo(self):
        self.client.force_login(self.utenti['ROSSI'])
        r = self.client.get(reverse('turni:home'))
        self.assertContains(r, 'aria-label="Chat')
        self.assertContains(r, reverse('turni:archivio'))  # riquadro Archivio in home (al posto di Tutte le funzioni)
        self.assertNotContains(r, 'aria-label="Esci"')
        self.assertContains(self.client.get(reverse('turni:miei_turni')), reverse('turni:logout'))


class NotificheConConfermaTest(TestCase):
    """Centro notifiche come Instagram: Conferma / Rifiuta con riepilogo e convalida."""

    def setUp(self):
        from django.utils import timezone

        from .models import Settimana

        self.domani = timezone.localdate() + timedelta(days=1)
        sett, _ = Settimana.objects.get_or_create(lunedi=self.domani - timedelta(days=self.domani.weekday()))
        self.dip = {}
        for nome, fascia in (('ROSSI MARIO', '1T'), ('BIANCHI LUCA', '2T')):
            d = Dipendente.objects.create(nome=nome)
            d.utente = get_user_model().objects.create_user(nome.split()[0].lower())
            d.save()
            Turno.objects.create(settimana=sett, dipendente=d, data=self.domani, fascia=fascia, postazione='IMP1',
                                 ruolo='OdL', posto='Impianto 1 · Operatore di Linea', incarichi='IMP1/OdL')
            self.dip[nome.split()[0]] = d

    def test_cambio_turno_conferma_dalla_notifica(self):
        from . import richieste as svc
        from .models import CambioTurno, Notifica

        c = svc.crea_cambio(self.dip['ROSSI'], self.dip['BIANCHI'], self.domani)
        self.client.force_login(self.dip['BIANCHI'].utente)
        r = self.client.get(reverse('turni:notifiche'))
        self.assertContains(r, 'Rossi Mario ti chiede un cambio turno')
        self.assertContains(r, 'Conferma')
        self.assertContains(r, 'Oggi')
        n = Notifica.objects.get(utente=self.dip['BIANCHI'].utente, tipo='cambio')
        url = reverse('turni:notifica_scelta', args=[n.tipo, n.oggetto_id, 'conferma'])
        self.assertContains(self.client.get(url), 'Se lo approva, i tuoi turni diventano')
        self.client.post(url)
        c.refresh_from_db()
        self.assertEqual(c.stato, CambioTurno.Stato.ATTESA_UFFICIO)
        self.assertTrue(Notifica.objects.filter(utente=self.dip['ROSSI'].utente, titolo__contains='ha accettato').exists())
        self.assertContains(self.client.get(reverse('turni:notifiche')), 'Hai confermato')

    def test_manutenzione_presa_in_carico_o_rifiutata(self):
        from . import manutenzione as mn
        from .models import Intervento, Macchina, Notifica

        pala = Macchina.objects.create(codice='P-T1', nome='Pala prova', luogo='PIAZZALE')
        richiedente = self.dip['ROSSI'].utente
        for scelta, stato_atteso in (('conferma', Intervento.Stato.ASSEGNATA), ('rifiuta', Intervento.Stato.SEGNALATA)):
            i = Intervento.objects.create(macchina=pala, descrizione='Gomma a terra', segnalata_da=richiedente,
                                          assegnata_a=self.dip['BIANCHI'])
            mn.avvisa([self.dip['BIANCHI'].utente_id], richiedente, 'Richiesta di manutenzione', 'Gomma a terra', '/',
                      tipo='manutenzione', oggetto_id=i.pk)
            n = Notifica.objects.filter(utente=self.dip['BIANCHI'].utente, oggetto_id=i.pk).get()
            self.client.force_login(self.dip['BIANCHI'].utente)
            self.client.post(reverse('turni:notifica_scelta', args=[n.tipo, n.oggetto_id, scelta]))
            i.refresh_from_db()
            self.assertEqual(i.stato, stato_atteso)
            if scelta == 'rifiuta':
                self.assertIsNone(i.assegnata_a)


class NotificheUnaPerRigaTest(TestCase):
    def test_pulizia_completata_si_conferma_dalla_notifica_del_capo_turno(self):
        from django.utils import timezone

        from .models import ElementoPulizia, Pulizia, Settimana

        oggi = timezone.localdate()
        sett, _ = Settimana.objects.get_or_create(lunedi=oggi - timedelta(days=oggi.weekday()))
        persone = {}
        for nome, capo in (('CAPO PROVA', True), ('OPERAIO PROVA', False)):
            d = Dipendente.objects.create(nome=nome)
            d.utente = get_user_model().objects.create_user(nome.split()[0].lower())
            d.save()
            persone[nome.split()[0]] = Turno.objects.create(settimana=sett, dipendente=d, data=oggi, fascia='1T',
                                                            postazione='IMP1', capoturno=capo)
        el = ElementoPulizia.objects.create(nome='Prova pavimento', tipo='ZONA', convalida='CT')
        p = Pulizia.objects.create(turno=persone['OPERAIO'], elemento=el, stato=Pulizia.Stato.FATTA, fatta_il=timezone.now())
        self.client.force_login(persone['CAPO'].dipendente.utente)
        r = self.client.get(reverse('turni:notifiche'))
        self.assertContains(r, 'Operaio Prova ha completato una pulizia')
        self.assertNotContains(r, 'Da fare')
        url = reverse('turni:notifica_scelta', args=['pulizia_ct', p.pk, 'conferma'])
        self.assertContains(self.client.get(url), 'va in archivio')
        self.client.post(url)
        p.refresh_from_db()
        self.assertEqual(p.stato, Pulizia.Stato.VERIFICATA)


class ManutenzioneCapoTurnoTest(TestCase):
    def test_in_corso_con_fermo_e_conclusa_con_ripartenza(self):
        from datetime import datetime

        from django.utils import timezone

        from .models import FermoImpianto, Intervento, Macchina

        u = get_user_model().objects.create_user('capo', is_staff=True)
        self.client.force_login(u)
        nastro = Macchina.objects.create(codice='N-T1', nome='Nastro prova', luogo='IMP1')
        self.assertContains(self.client.get(reverse('turni:mn_in_corso') + '?luogo=IMP1'), 'Nastro prova')
        # senza fermo: solo la manutenzione in corso
        self.client.post(reverse('turni:mn_in_corso'), {'luogo': 'IMP1', 'macchina': nastro.pk, 'descrizione': 'Ingrassaggio'})
        self.assertFalse(FermoImpianto.objects.exists())
        # con fermo dalle 10:05 di oggi
        dal = timezone.localtime().replace(hour=0, minute=5, second=0, microsecond=0)
        self.client.post(reverse('turni:mn_in_corso'), {'luogo': 'IMP1', 'macchina': nastro.pk, 'descrizione': 'Cambio cuscinetto',
                                                         'fermo': '1', 'impianto': 'IMP1', 'dal': dal.strftime('%Y-%m-%dT%H:%M')})
        f = FermoImpianto.objects.get()
        self.assertEqual((f.causa, f.intervento.descrizione, timezone.localtime(f.fermo_dal).strftime('%H:%M')),
                         ('MANUTENZ', 'Cambio cuscinetto', '00:05'))
        r = self.client.get(reverse('turni:mn_conclusa'))
        self.assertContains(r, 'Ingrassaggio')
        self.assertContains(r, 'Impianto 1 fermo')
        self.assertContains(self.client.get(reverse('turni:mn_concludi', args=[f.intervento.pk])), 'Ripartenza impianto')
        self.client.post(reverse('turni:mn_concludi', args=[f.intervento.pk]), {'lavoro': 'Cuscinetto nuovo', 'riparte': '1',
                                                                                'ripartito': timezone.localtime().strftime('%Y-%m-%dT%H:%M')})
        f.refresh_from_db()
        self.assertIsNotNone(f.ripartito_il)
        self.assertEqual(f.intervento.stato, Intervento.Stato.COMPLETATA)


class ProgrammaTest(TestCase):
    def setUp(self):
        from django.utils import timezone

        from .models import Settimana

        self.giorno = timezone.localdate() + timedelta(days=1)
        sett, _ = Settimana.objects.get_or_create(lunedi=self.giorno - timedelta(days=self.giorno.weekday()))
        self.persone = {}
        for nome, capo in (('CAPO DOMANI', True), ('OPERAIO DOMANI', False)):
            d = Dipendente.objects.create(nome=nome)
            d.utente = get_user_model().objects.create_user(nome.split()[0].lower())
            d.save()
            Turno.objects.create(settimana=sett, dipendente=d, data=self.giorno, fascia='2T', postazione='IMP1', capoturno=capo)
            self.persone[nome.split()[0]] = d
        self.uff = get_user_model().objects.create_user('uff', is_staff=True)
        self.client.force_login(self.uff)

    def test_manutenzione_senza_fermo(self):
        from .models import Comunicazione, Intervento, Macchina

        m = Macchina.objects.create(codice='V-T1', nome='Vaglio prova', luogo='IMP1')
        self.client.post(reverse('turni:programma', args=['manutenzione']),
                         {'luogo': 'IMP1', 'macchina': m.pk, 'descrizione': 'Rulli', 'giorno': self.giorno.isoformat(), 'turno': '2T'})
        i = Intervento.objects.get(macchina=m)
        self.assertEqual((i.tipo, i.da_fare_il), ('PROGRAMMATA', self.giorno))
        self.assertFalse(Comunicazione.objects.filter(tipo='FERMO', macchina=m).exists())

    def test_pulizia_con_fermo_in_una_fascia_avvisa_gli_interessati(self):
        from django.utils import timezone

        from .models import Comunicazione, Notifica, Pulizia

        self.client.post(reverse('turni:programma', args=['pulizia']),
                         {'luogo': 'IMP1', 'descrizione': 'Tramoggia', 'giorno': self.giorno.isoformat(), 'turno': '2T',
                          'fermo': '1', 'impianto': 'IMP1', 'dalle': '15:00', 'alle': '17:30'})
        p = Pulizia.objects.get()
        self.assertEqual(p.turno.dipendente, self.persone['CAPO'])
        c = Comunicazione.objects.get(tipo='FERMO', testo='Tramoggia')
        self.assertEqual((c.tipo, c.motivo, timezone.localtime(c.dal).strftime('%H:%M'), timezone.localtime(c.al).strftime('%H:%M')),
                         ('FERMO', 'PULIZIA', '15:00', '17:30'))
        for d in self.persone.values():
            self.assertTrue(Notifica.objects.filter(utente=d.utente, titolo__startswith='Fermo programmato').exists())
