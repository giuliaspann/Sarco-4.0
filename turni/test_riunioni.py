"""Riunioni in ufficio: programmazione, notifica con Conferma / Rifiuta, riquadro nella settimana dei turni."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Dipendente, InvitoRiunione, Notifica, Riunione


@override_settings(PUSH_SINCRONO=True)
class RiunioniTest(TestCase):
    def setUp(self):
        U = get_user_model()
        self.uff = U.objects.create_user('uff', is_staff=True)
        self.dip = {}
        for nome in ('ROSSI MARIO', 'BIANCHI LUCA', 'VERDI ANNA'):
            d = Dipendente.objects.create(nome=nome, utente=U.objects.create_user(nome.split()[0].lower()))
            self.dip[nome.split()[0]] = d
        self.giorno = timezone.localdate() + timedelta(days=1)

    def programma(self, invitati):
        self.client.force_login(self.uff)
        return self.client.post(reverse('turni:riunione_nuova'), {
            'titolo': 'Riunione sicurezza', 'luogo': 'Ufficio', 'giorno': self.giorno.isoformat(),
            'dalle': '10:00', 'alle': '11:00', 'invitati': [d.pk for d in invitati]})

    def test_programma_e_notifica_gli_invitati(self):
        self.programma([self.dip['ROSSI'], self.dip['BIANCHI']])
        r = Riunione.objects.get()
        self.assertEqual(r.inviti.count(), 2)
        n = Notifica.objects.get(utente=self.dip['ROSSI'].utente)
        self.assertEqual((n.tipo, n.mittente), ('riunione', self.uff))
        self.assertFalse(Notifica.objects.filter(utente=self.dip['VERDI'].utente).exists())

    def test_operaio_non_puo_programmare(self):
        self.client.force_login(self.dip['ROSSI'].utente)
        self.assertEqual(self.client.get(reverse('turni:riunione_nuova')).status_code, 403)

    def test_conferma_dalla_notifica_e_riquadro_nella_settimana(self):
        self.programma([self.dip['ROSSI']])
        inv = InvitoRiunione.objects.get()
        self.client.force_login(self.dip['ROSSI'].utente)
        pagina = self.client.get(reverse('turni:notifiche')).content.decode()
        self.assertIn('Riunione sicurezza', pagina)
        self.assertIn(reverse('turni:notifica_scelta', args=['riunione', inv.pk, 'conferma']), pagina)
        # prima della risposta il riquadro c'è, "da confermare"
        settimana = self.client.get(reverse('turni:miei_turni') + f'?settimana={self.giorno.isoformat()}').content.decode()
        self.assertIn('rn-riquadro', settimana)
        self.assertIn('Da confermare', settimana)
        self.client.post(reverse('turni:notifica_scelta', args=['riunione', inv.pk, 'conferma']))
        inv.refresh_from_db()
        self.assertEqual(inv.risposta, 'si')
        settimana = self.client.get(reverse('turni:miei_turni') + f'?settimana={self.giorno.isoformat()}').content.decode()
        self.assertIn('Partecipi', settimana)
        # chi l'ha programmata viene avvisato
        self.assertTrue(Notifica.objects.filter(utente=self.uff, titolo__contains='partecipa').exists())

    def test_rifiuta_toglie_il_riquadro(self):
        self.programma([self.dip['BIANCHI']])
        inv = InvitoRiunione.objects.get()
        self.client.force_login(self.dip['BIANCHI'].utente)
        self.client.post(reverse('turni:notifica_scelta', args=['riunione', inv.pk, 'rifiuta']))
        inv.refresh_from_db()
        self.assertEqual(inv.risposta, 'no')
        settimana = self.client.get(reverse('turni:miei_turni') + f'?settimana={self.giorno.isoformat()}').content.decode()
        self.assertNotIn('rn-riquadro', settimana)

    def test_dettaglio_per_ufficio_e_annulla(self):
        self.programma([self.dip['ROSSI'], self.dip['VERDI']])
        r = Riunione.objects.get()
        pagina = self.client.get(reverse('turni:riunione', args=[r.pk])).content.decode()
        self.assertIn('2 da confermare', pagina)
        self.client.post(reverse('turni:riunione', args=[r.pk]), {'azione': 'annulla'})
        r.refresh_from_db()
        self.assertTrue(r.annullata)
        self.assertTrue(Notifica.objects.filter(utente=self.dip['VERDI'].utente, titolo__startswith='Riunione annullata').exists())

    def test_non_invitato_non_vede_il_dettaglio(self):
        self.programma([self.dip['ROSSI']])
        self.client.force_login(self.dip['VERDI'].utente)
        self.assertEqual(self.client.get(reverse('turni:riunione', args=[Riunione.objects.get().pk])).status_code, 403)

    def test_orario_sbagliato(self):
        self.client.force_login(self.uff)
        self.client.post(reverse('turni:riunione_nuova'), {
            'titolo': 'X', 'giorno': self.giorno.isoformat(), 'dalle': '11:00', 'alle': '10:00', 'invitati': [self.dip['ROSSI'].pk]})
        self.assertFalse(Riunione.objects.exists())
