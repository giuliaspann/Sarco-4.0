"""Prova chiesta dall'utente: la "Pulizia Pala" di Spanò Giulia torna da completare (turni dal 19 al 21 ottobre 2026)."""

from datetime import date

from django.db import migrations

LAVORO = {'1T', '2T', 'N', 'G', 'ALTRO'}


def riapri(apps, schema_editor):
    Dipendente = apps.get_model('turni', 'Dipendente')
    Elemento = apps.get_model('turni', 'ElementoPulizia')
    Pulizia = apps.get_model('turni', 'Pulizia')
    giulia = Dipendente.objects.filter(nome__icontains='GIULIA').filter(nome__icontains='SPAN').first()
    if not giulia:
        return
    pala = Elemento.objects.filter(nome__iexact='Pala gommata').first() or Elemento.objects.filter(nome__iexact='Pala').first()
    if not pala:
        pala = Elemento.objects.create(nome='Pala', tipo='MEZZO', luogo='MEZZI',
                                       istruzioni='Togli il vetro da gradini e cabina, pulisci i vetri e la benna.')
    for t in giulia.turni.filter(data__range=(date(2026, 10, 19), date(2026, 10, 21)), fascia__in=LAVORO):
        p, _ = Pulizia.objects.get_or_create(turno=t, elemento=pala)
        p.stato, p.fatta_il, p.nota, p.verificata_da, p.verificata_il, p.nota_verifica = 'DA_FARE', None, '', None, None, ''
        p.save()


class Migration(migrations.Migration):
    dependencies = [('turni', '0041_nome_segnaletica')]
    operations = [migrations.RunPython(riapri, migrations.RunPython.noop)]
