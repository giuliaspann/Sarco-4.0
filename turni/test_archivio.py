import shutil
import tempfile
from datetime import timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import (Dipendente, Fascia, FermoImpianto, Intervento, Macchina, Postazione, Pulizia, SaldoFerie, Settimana,
                     Turno)
from .views_archivio import SEZIONI

MEDIA = tempfile.mkdtemp()


def foto():
    buf = BytesIO()
    Image.new('RGB', (60, 40), 'red').save(buf, 'JPEG')
    return SimpleUploadedFile('f.jpg', buf.getvalue(), content_type='image/jpeg')


@override_settings(MEDIA_ROOT=MEDIA)
class ArchivioTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        User = get_user_model()
        self.oggi = timezone.localdate()
        self.u = User.objects.create_user('operaio', password='123456')
        self.dip = Dipendente.objects.create(nome='ROSSI MARCO', utente=self.u)
        self.altro = Dipendente.objects.create(nome='VERDI LUCA')
        self.ufficio = User.objects.create_user('ufficio', password='123456', is_staff=True)
        sett = Settimana.objects.create(lunedi=self.oggi - timedelta(days=self.oggi.weekday()))
        self.t1 = Turno.objects.create(settimana=sett, dipendente=self.dip, data=self.oggi, codice='1T', fascia=Fascia.MATTINA,
                                       postazione=Postazione.IMP1)
        self.p = Pulizia.objects.create(turno=self.t1, stato=Pulizia.Stato.VERIFICATA, fatta_il=timezone.now(), foto=foto(),
                                        nota='Nastro pulito')
        m = Macchina.objects.create(codice='N1', nome='Nastro 1', luogo='IMP2')
        self.i = Intervento.objects.create(macchina=m, descrizione='Rumore strano', segnalata_da=self.u, foto_guasto=foto())
        FermoImpianto.objects.create(impianto='IMP1', causa='NASTRO', segnalato_da=self.u)
        SaldoFerie.objects.create(dipendente=self.dip, al=self.oggi - timedelta(days=30), ferie_ore=80, rol_ore=16)
        self.client.login(username='operaio', password='123456')

    def test_ogni_sezione_si_apre_e_scarica_il_pdf(self):
        for sezione in SEZIONI:
            r = self.client.get(reverse('turni:archivio_cerca', args=[sezione]))
            self.assertEqual(r.status_code, 200, sezione)
            r = self.client.get(reverse('turni:archivio_pdf', args=[sezione]))
            self.assertEqual(r['Content-Type'], 'application/pdf', sezione)
            self.assertTrue(r.content.startswith(b'%PDF-1.4') and r.content.rstrip().endswith(b'%%EOF'), sezione)

    def test_filtri_e_foto_nel_pdf(self):
        url = reverse('turni:archivio_cerca', args=['pulizie'])
        self.assertContains(self.client.get(url), 'Nastro pulito')
        self.assertNotContains(self.client.get(url, {'impianto': 'IMP2'}), 'Nastro pulito')
        self.assertNotContains(self.client.get(url, {'turno': '2T'}), 'Nastro pulito')
        ieri = self.oggi - timedelta(days=1)
        self.assertNotContains(self.client.get(url, {'dal': ieri - timedelta(days=5), 'al': ieri}), 'Nastro pulito')
        pdf = self.client.get(reverse('turni:archivio_pdf', args=['pulizie'])).content
        self.assertIn(b'/Subtype /Image', pdf)
        self.assertIn(b'Nastro pulito', pdf)
        man = self.client.get(reverse('turni:archivio_cerca', args=['manutenzione']), {'impianto': 'IMP2'})
        self.assertContains(man, 'Rumore strano')

    def test_periodo_massimo_tre_mesi(self):
        r = self.client.get(reverse('turni:archivio_cerca', args=['fermi']), {'dal': '2020-01-01', 'al': self.oggi})
        self.assertContains(r, 'Al massimo 3 mesi')

    def test_il_dipendente_vede_solo_se_stesso(self):
        self.assertRedirects(self.client.get(reverse('turni:archivio_dipendenti')),
                             reverse('turni:archivio_dipendente', args=[self.dip.pk]))
        r = self.client.get(reverse('turni:archivio_dipendente', args=[self.dip.pk]))
        self.assertNotContains(r, 'Ferie residue')  # saldo tolto dall'app (10/11/2026)
        self.assertEqual(r.context['s']['n_segnalazioni'], 2)
        self.assertEqual(len(r.context['s']['pulizie']), 1)
        self.assertEqual(self.client.get(reverse('turni:archivio_dipendente', args=[self.altro.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse('turni:archivio_dipendente_pdf', args=[self.altro.pk])).status_code, 403)

    def test_l_ufficio_vede_tutti(self):
        self.client.login(username='ufficio', password='123456')
        self.assertContains(self.client.get(reverse('turni:archivio_dipendenti'), {'q': 'verdi'}), 'Verdi Luca')
        r = self.client.get(reverse('turni:archivio_dipendente_pdf', args=[self.dip.pk]), {'dal': self.oggi.replace(day=1), 'al': self.oggi})
        self.assertEqual(r['Content-Type'], 'application/pdf')
        self.assertIn(b'Rossi Marco', r.content)
