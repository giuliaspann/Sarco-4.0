import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Dipendente, Documento, LetturaDocumento, Scadenza
from .views_documenti import da_leggere, dipendente_dal_nome_file

CARTELLA = tempfile.mkdtemp()


def pdf(nome):
    return SimpleUploadedFile(nome, b'%PDF-1.4 prova', content_type='application/pdf')


@override_settings(MEDIA_ROOT=CARTELLA)
class DocumentiTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(CARTELLA, ignore_errors=True)

    def setUp(self):
        User = get_user_model()
        self.rossi = Dipendente.objects.create(nome='ROSSI MARIO', utente=User.objects.create_user('rossi', password='x'))
        self.bianchi = Dipendente.objects.create(nome='BIANCHI LUCA', utente=User.objects.create_user('bianchi', password='x'))
        self.ufficio = User.objects.create_user('ufficio', password='x', is_staff=True)

    def carica(self, **dati):
        self.client.login(username='ufficio', password='x')
        dati.setdefault('categoria', 'CEDOLINO')
        return self.client.post(reverse('turni:ufficio_documenti'), dati)

    def test_riconosce_dal_nome_file(self):
        dip = [self.rossi, self.bianchi]
        self.assertEqual(dipendente_dal_nome_file('ROSSI_MARIO_09-2026.pdf', dip), self.rossi)
        self.assertEqual(dipendente_dal_nome_file('cedolino bianchi luca.pdf', dip), self.bianchi)
        self.assertIsNone(dipendente_dal_nome_file('ROSSI_09-2026.pdf', dip))

    def test_cedolini_del_mese_a_ciascuno_il_suo(self):
        r = self.carica(destinatario='auto', file=[pdf('ROSSI_MARIO_09.pdf'), pdf('BIANCHI_LUCA_09.pdf')], titolo='Cedolino settembre')
        self.assertEqual(r.status_code, 302)
        doc_rossi = Documento.objects.get(dipendente=self.rossi)
        doc_bianchi = Documento.objects.get(dipendente=self.bianchi)
        self.assertNotIn('ROSSI', doc_rossi.file.name)  # nome casuale nel volume

        self.client.login(username='rossi', password='x')
        self.assertEqual(da_leggere(self.rossi), 1)
        r = self.client.get(reverse('turni:documenti'))
        self.assertContains(r, 'Cedolino settembre')
        self.assertEqual(self.client.get(reverse('turni:documento_file', args=[doc_rossi.pk])).status_code, 200)
        self.assertEqual(da_leggere(self.rossi), 0)
        # il cedolino del collega no
        self.assertEqual(self.client.get(reverse('turni:documento_file', args=[doc_bianchi.pk])).status_code, 403)

    def test_nome_non_riconosciuto_non_carica_niente(self):
        self.carica(destinatario='auto', file=[pdf('ROSSI_MARIO.pdf'), pdf('VERDI.pdf')])
        self.assertFalse(Documento.objects.exists())

    def test_formato_non_accettato(self):
        self.carica(destinatario=self.rossi.pk, file=[SimpleUploadedFile('virus.exe', b'MZ')])
        self.assertFalse(Documento.objects.exists())

    def test_documento_aziendale_e_presa_visione(self):
        self.carica(destinatario='tutti', categoria='REGOLAMENTO', titolo='Regolamento DPI', chiedi_presa_visione='on', file=[pdf('dpi.pdf')])
        doc = Documento.objects.get()
        self.assertTrue(doc.aziendale)
        self.client.login(username='bianchi', password='x')
        self.assertEqual(self.client.get(reverse('turni:documento_file', args=[doc.pk])).status_code, 200)
        self.assertEqual(da_leggere(self.bianchi), 1)  # aperto ma senza conferma
        self.client.post(reverse('turni:presa_visione_documento', args=[doc.pk]))
        self.assertIsNotNone(LetturaDocumento.objects.get(dipendente=self.bianchi).presa_visione_il)
        self.assertEqual(da_leggere(self.bianchi), 0)
        self.assertEqual(da_leggere(self.rossi), 1)

    def test_solo_ufficio_carica(self):
        self.client.login(username='rossi', password='x')
        r = self.client.post(reverse('turni:ufficio_documenti'), {'destinatario': 'tutti', 'categoria': 'ALTRO', 'file': [pdf('a.pdf')]})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Documento.objects.exists())

    def test_torna_solo_pagine_interne(self):
        r = self.carica(destinatario=self.rossi.pk, file=[pdf('a.pdf')], torna='https://esempio.it/')
        self.assertRedirects(r, reverse('turni:ufficio_documenti'), fetch_redirect_response=False)

    def test_scheda_e_scadenze(self):
        self.client.login(username='ufficio', password='x')
        url = reverse('turni:scheda_dipendente', args=[self.rossi.pk])
        self.client.post(url, {'azione': 'anagrafica', 'tipo_contratto': 'DETERMINATO', 'livello': '3', 'scadenza_contratto': '2026-12-31', 'email': ''})
        self.rossi.refresh_from_db()
        self.assertEqual(self.rossi.tipo_contratto, 'DETERMINATO')
        domani = timezone.localdate() + timedelta(days=1)
        self.client.post(url, {'azione': 'scadenza', 'tipo': 'VISITA', 'scade_il': domani.isoformat()})
        self.assertEqual(Scadenza.objects.get().dipendente, self.rossi)
        r = self.client.get(reverse('turni:dipendenti'))
        self.assertContains(r, 'Scadenze entro 30 giorni')
        self.assertContains(r, 'Visita medica')
        self.assertContains(self.client.get(url), 'Anagrafica e contratto')
        self.assertContains(self.client.get(reverse('turni:ufficio_documenti')), 'Carica documenti')
        self.client.login(username='rossi', password='x')
        self.assertEqual(self.client.get(url).status_code, 302)  # verso il login dell'admin
