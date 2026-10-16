"""Eseguito da Railway prima di ogni deploy: migrazioni e primo utente dell'ufficio.

L'utente si crea solo se non esiste ancora, da SARCO_ADMIN_USER e SARCO_ADMIN_PASSWORD
(variabili del servizio su Railway). Ai deploy successivi non viene toccato: la password
si cambia da /admin/.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Migrazioni + creazione del primo utente ufficio (superuser) dalle variabili d\'ambiente'

    def handle(self, *args, **opzioni):
        call_command('migrate', interactive=False)

        username = os.environ.get('SARCO_ADMIN_USER', '').strip()
        password = os.environ.get('SARCO_ADMIN_PASSWORD', '')
        if not username or not password:
            self.stdout.write('SARCO_ADMIN_USER/SARCO_ADMIN_PASSWORD non impostate: nessun utente creato.')
            return
        User = get_user_model()
        if User.objects.filter(username=username).exists():
            self.stdout.write(f'Utente ufficio "{username}" già presente.')
            return
        User.objects.create_superuser(username=username, email='', password=password)
        self.stdout.write(self.style.SUCCESS(f'Creato utente ufficio "{username}".'))
