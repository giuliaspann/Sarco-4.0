"""Prova chiesta dall'utente: una "Pulizia Pala" assegnata a Spanò Giulia (palista di notte) per vedere
come appare la sezione Pulizie. Tocca solo i suoi turni lavorativi dal 19 al 21 ottobre 2026."""

from datetime import date

from django.db import migrations

LAVORO = {'1T', '2T', 'N', 'G', 'ALTRO'}


def crea(apps, schema_editor):
    Dipendente = apps.get_model('turni', 'Dipendente')
    Elemento = apps.get_model('turni', 'ElementoPulizia')
    Pulizia = apps.get_model('turni', 'Pulizia')
    giulia = Dipendente.objects.filter(nome__icontains='GIULIA').filter(nome__icontains='SPAN').first()
    if not giulia:
        return
    pala = Elemento.objects.filter(nome__iexact='Pala gommata').first() or Elemento.objects.get_or_create(
        nome='Pala', defaults={'tipo': 'MEZZO', 'istruzioni': 'Togli il vetro da gradini e cabina, pulisci i vetri e la benna.'})[0]
    for t in giulia.turni.filter(data__range=(date(2026, 10, 19), date(2026, 10, 21)), fascia__in=LAVORO):
        Pulizia.objects.get_or_create(turno=t, elemento=pala)


class Migration(migrations.Migration):
    dependencies = [('turni', '0035_foto_prima')]
    operations = [migrations.RunPython(crea, migrations.RunPython.noop)]
