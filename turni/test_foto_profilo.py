import shutil
import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import Dipendente

MEDIA = tempfile.mkdtemp()


def immagine(larga=800, alta=500, formato='JPEG'):
    buf = BytesIO()
    Image.new('RGB', (larga, alta), 'green').save(buf, formato)
    return SimpleUploadedFile('io.jpg', buf.getvalue(), content_type='image/jpeg')


@override_settings(MEDIA_ROOT=MEDIA)
class FotoProfiloTest(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA, ignore_errors=True)

    def setUp(self):
        User = get_user_model()
        self.u = User.objects.create_user('rossi', password='123456')
        self.dip = Dipendente.objects.create(nome='ROSSI MARCO', utente=self.u)
        self.collega = Dipendente.objects.create(nome='VERDI LUCA', utente=User.objects.create_user('verdi', password='123456'))
        self.estraneo = User.objects.create_user('esterno', password='123456')
        self.client.login(username='rossi', password='123456')

    def test_carica_ritaglia_e_mostra(self):
        r = self.client.post(reverse('turni:foto_profilo'), {'foto': immagine()})
        self.assertRedirects(r, reverse('turni:miei_turni'), fetch_redirect_response=False)
        self.dip.refresh_from_db()
        self.assertTrue(self.dip.foto)
        with Image.open(self.dip.foto.path) as img:
            self.assertEqual(img.size, (400, 400))  # quadrata per il cerchietto
        # la foto compare nel cerchietto dell'Area personale e nella barra in basso
        url = reverse('turni:foto_profilo_img', args=[self.dip.pk])
        self.assertContains(self.client.get(reverse('turni:miei_turni')), url, count=2)
        # una seconda foto prende il posto della prima, senza lasciarla sul disco
        vecchia = self.dip.foto.path
        self.client.post(reverse('turni:foto_profilo'), {'foto': immagine(300, 600)})
        self.dip.refresh_from_db()
        self.assertNotEqual(self.dip.foto.path, vecchia)
        self.assertFalse(self.dip.foto.storage.exists(vecchia))

    def test_file_non_valido(self):
        brutto = SimpleUploadedFile('x.jpg', b'non sono una foto', content_type='image/jpeg')
        r = self.client.post(reverse('turni:foto_profilo'), {'foto': brutto}, follow=True)
        self.assertContains(r, 'Non riesco a leggere questa foto')
        self.dip.refresh_from_db()
        self.assertFalse(self.dip.foto)

    def test_chi_la_vede(self):
        self.client.post(reverse('turni:foto_profilo'), {'foto': immagine()})
        url = reverse('turni:foto_profilo_img', args=[self.dip.pk])
        self.client.login(username='verdi', password='123456')
        self.assertEqual(self.client.get(url).status_code, 200)  # un collega sì
        self.client.login(username='esterno', password='123456')
        self.assertEqual(self.client.get(url).status_code, 403)  # chi non è dipendente né ufficio no
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)  # senza accesso: alla pagina di login
        self.client.login(username='verdi', password='123456')
        self.assertEqual(self.client.get(reverse('turni:foto_profilo_img', args=[self.collega.pk])).status_code, 404)

    def test_solo_post(self):
        self.assertEqual(self.client.get(reverse('turni:foto_profilo')).status_code, 405)
