"""Manda adesso gli avvisi delle pulizie arrivati all'ora giusta (di solito lo fa il server da solo, ogni minuto)."""

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Avvisi automatici delle pulizie (ottiche, pozzetti, vagli, Incolore, carrelli)'

    def handle(self, *args, **opzioni):
        from turni.piano_pulizie import controlla

        self.stdout.write(f'Avvisi mandati: {controlla()}')
