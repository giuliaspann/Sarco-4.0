from datetime import date

from django.db import migrations


def avanti(apps, schema_editor):
    """Regole aggiornate del foglio (Giulia, 11/11/2026): macchine ottiche a due operatori competenti (MO 1, poi 2),
    pavimentazione agli altri, rotovaglio anche in 1T, Capi Turno senza pulizie.
    Le pulizie ancora da fare create con le regole vecchie si tolgono: l'app le ricrea con le nuove."""
    from turni.regole_foglio import applica

    Elemento = apps.get_model('turni', 'ElementoPulizia')
    applica(Elemento, apps.get_model('turni', 'RegolaPulizia'))
    Pulizia = apps.get_model('turni', 'Pulizia')
    oggi = date.today()
    da_rifare = Pulizia.objects.filter(stato='DA_FARE', richiesta_da__isnull=True, fatta_il__isnull=True, turno__data__gte=oggi)
    da_rifare.filter(elemento__nome__in=['Macchine ottiche', 'Pavimentazione + altro', 'Generiche Rotovaglio']).delete()
    da_rifare.filter(turno__capoturno=True, elemento__isnull=False).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('turni', '0070_competenza_mo'),
    ]

    operations = [
        migrations.RunPython(avanti, migrations.RunPython.noop),
    ]
