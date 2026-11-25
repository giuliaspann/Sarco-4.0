"""Le richieste di pulizia approvate prima del 25/11/2026 non ricordavano la pulizia nata dall'approvazione: nell'archivio
«Richieste di pulizia» comparivano due volte. Le colleghiamo: stessa persona che ha approvato, stesso giorno, e la nota
della pulizia che comincia con «<area>: <testo della richiesta>» (come la scrive approva_richiesta)."""

from django.db import migrations



def collega(apps, schema_editor):
    Straordinaria = apps.get_model('turni', 'Straordinaria')
    Pulizia = apps.get_model('turni', 'Pulizia')
    from turni.models import Luogo

    usate = set(Straordinaria.objects.exclude(pulizia__isnull=True).values_list('pulizia_id', flat=True))
    for s in Straordinaria.objects.filter(stato='INOLTRATA', pulizia__isnull=True).order_by('gestita_il'):
        nome = Luogo(s.luogo).label if s.luogo in Luogo.values else s.luogo
        inizio = f'{nome}: {s.testo}'[:60]
        p = (Pulizia.objects.filter(richiesta_da_id=s.gestita_da_id, elemento__isnull=True, turno__data=s.giorno,
                                    nota__startswith=inizio).exclude(pk__in=usate).order_by('pk').first())
        if p:
            s.pulizia_id = p.pk
            s.save(update_fields=['pulizia'])
            usate.add(p.pk)


class Migration(migrations.Migration):
    dependencies = [('turni', '0092_richiesta_pulizia_collegata')]

    operations = [migrations.RunPython(collega, migrations.RunPython.noop)]
