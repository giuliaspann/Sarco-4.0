import os
import sys

from django.apps import AppConfig


def _e_il_server():
    """Solo il server vero (gunicorn su Railway, runserver in locale): non i test, le migrazioni o i comandi."""
    if os.environ.get('AVVISI_PULIZIE', '1') == '0':
        return False
    comando = ' '.join(sys.argv)
    if 'gunicorn' in os.path.basename(sys.argv[0] or '') or 'gunicorn' in comando.split(' ')[0]:
        return True
    if 'runserver' in sys.argv:
        return '--noreload' in sys.argv or os.environ.get('RUN_MAIN') == 'true'
    return False


class TurniConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'turni'

    def ready(self):
        # avvisi automatici delle pulizie (ottiche a metà turno, pozzetti entro le 7…): un controllo al minuto
        if _e_il_server():
            from .piano_pulizie import avvia_controllo

            avvia_controllo()
