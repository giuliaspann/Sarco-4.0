"""Correzioni del giro bug prima della presentazione del 25/11/2026."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Chat, MessaggioChat, Sondaggio
from .views_messaggi import anteprima


class AnteprimaSondaggioTest(TestCase):
    def test_elenco_chat_mostra_la_domanda_del_sondaggio(self):
        utente = get_user_model().objects.create_user('prova.sondaggio')
        chat = Chat.objects.create(nome='Prova')
        m = MessaggioChat.objects.create(chat=chat, autore=utente, testo='')
        Sondaggio.objects.create(messaggio=m, domanda='Riunione: quale giorno?')
        self.assertEqual(anteprima(m), '📊 Riunione: quale giorno?')

    def test_messaggio_di_testo_invariato(self):
        utente = get_user_model().objects.create_user('prova.testo')
        m = MessaggioChat.objects.create(chat=Chat.objects.create(nome='Prova'), autore=utente, testo='Ciao')
        self.assertEqual(anteprima(m), 'Ciao')


class CronologiaPuliziaTest(TestCase):
    def test_la_cronologia_non_mostra_l_avviso(self):
        from datetime import date

        from .models import Dipendente, ElementoPulizia, Pulizia, Settimana, Turno
        from .views_pulizie_piano import passaggi

        e = ElementoPulizia.objects.filter(avviso=True).first() or ElementoPulizia.objects.first()
        d = Dipendente.objects.create(nome='PROVA CRONOLOGIA')
        s = Settimana.objects.create(lunedi=date(2026, 11, 23))
        t = Turno.objects.create(settimana=s, dipendente=d, data=date(2026, 11, 24), fascia='1T', postazione='IMP1')
        p = Pulizia.objects.create(turno=t, elemento=e)
        testi = [s['testo'] for s in passaggi([p])]
        self.assertFalse(any(x.startswith('Avviso') for x in testi), testi)
        self.assertTrue(testi)


class AvvisoRitardoTest(TestCase):
    """Ritardo e uscita arrivano a ufficio, responsabile piazzale, responsabile impianto e Capo Turno dell'Impianto 1."""

    def test_destinatari(self):
        from datetime import date
        from unittest import mock

        from django.contrib.auth.models import Permission
        from django.urls import reverse

        from .models import AvvisoAssenza, Dipendente, Notifica, Settimana, Turno

        U = get_user_model()

        def persona(nome, **campi):
            d = Dipendente.objects.create(nome=nome, utente=U.objects.create_user(nome.lower().replace(' ', '.')), **campi)
            return d

        op = persona('OPERAIO UNO')
        ct = persona('CAPO TURNO')
        ct2 = persona('CAPO ALTRO')
        rp = persona('RESP PIAZZALE', resp_piazzale=True)
        ri = persona('RESP IMPIANTO', resp_impianto=True)
        uff = persona('UFFICIO TURNI')
        uff.utente.user_permissions.add(Permission.objects.get(codename='approva_richieste'))
        estraneo = persona('ALTRO OPERAIO')
        s = Settimana.objects.create(lunedi=date(2026, 11, 23))
        g = date(2026, 11, 25)
        Turno.objects.create(settimana=s, dipendente=op, data=g, fascia='1T', postazione='IMP1')
        Turno.objects.create(settimana=s, dipendente=ct, data=g, fascia='1T', postazione='IMP1', capoturno=True)
        Turno.objects.create(settimana=s, dipendente=ct2, data=g, fascia='2T', postazione='IMP1', capoturno=True)
        Turno.objects.create(settimana=s, dipendente=estraneo, data=g, fascia='1T', postazione='IMP1')
        self.client.force_login(op.utente)
        with mock.patch('turni.push._invia_ora'), mock.patch('django.utils.timezone.localdate', return_value=g):
            self.client.post(reverse('turni:nuovo_avviso'), {'data': g.isoformat(), 'tipo': 'RITARDO', 'alle': '07:30'})
        self.assertEqual(AvvisoAssenza.objects.count(), 1)
        avvisati = set(Notifica.objects.values_list('utente_id', flat=True))
        self.assertEqual(avvisati, {ct.utente_id, rp.utente_id, ri.utente_id, uff.utente_id})

    def test_fuori_impianto_1_niente_capo_turno(self):
        from datetime import date

        from .models import AvvisoAssenza, Dipendente, Settimana, Turno
        from .richieste import destinatari_avviso_assenza

        U = get_user_model()
        op = Dipendente.objects.create(nome='OPERAIO DUE', utente=U.objects.create_user('op.due'))
        ct = Dipendente.objects.create(nome='CAPO DUE', utente=U.objects.create_user('capo.due'))
        s = Settimana.objects.create(lunedi=date(2026, 11, 23))
        g = date(2026, 11, 25)
        Turno.objects.create(settimana=s, dipendente=op, data=g, fascia='1T', postazione='IMP2')
        Turno.objects.create(settimana=s, dipendente=ct, data=g, fascia='1T', postazione='IMP2', capoturno=True)
        a = AvvisoAssenza.objects.create(dipendente=op, data=g, tipo='RITARDO')
        self.assertNotIn(ct.utente_id, destinatari_avviso_assenza(a))


class MenuPuliziaPerTuttiTest(TestCase):
    """«Tutti devono vedere tutto» (Giulia, 24/11/2026): i quattro tasti della pagina Pulizia per ogni account."""

    TASTI = ('Calendario pulizie', 'In corso adesso', 'Richiedi pulizia', 'Pulizia straordinaria')

    def controlla(self, utente):
        from django.urls import reverse

        self.client.force_login(utente)
        r = self.client.get(reverse('turni:pulizie'))
        self.assertEqual(r.status_code, 200)
        for t in self.TASTI:
            self.assertContains(r, t)

    def test_senza_scheda_dipendente(self):
        self.controlla(get_user_model().objects.create_user('senza.scheda'))

    def test_dipendente_senza_turno_oggi(self):
        from .models import Dipendente

        d = Dipendente.objects.create(nome='PROVA RIPOSO', utente=get_user_model().objects.create_user('prova.riposo'))
        self.controlla(d.utente)
