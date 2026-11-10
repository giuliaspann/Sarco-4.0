from django.db import migrations

# chi lavora in laboratorio (Giulia, 10/11/2026): vede il tasto "Analisi"
ANALISTI = ('GALASSI', 'GENESIO', 'ODDO')


def avanti(apps, schema_editor):
    Dipendente = apps.get_model('turni', 'Dipendente')
    for cognome in ANALISTI:
        for d in Dipendente.objects.filter(nome__startswith=cognome + ' '):
            mansioni = [m for m in d.mansione.split(',') if m]
            if 'ANALISTA' not in mansioni:
                d.mansione = ','.join(mansioni + ['ANALISTA'])
                d.save(update_fields=['mansione'])


class Migration(migrations.Migration):
    dependencies = [
        ('turni', '0059_dipendente_foto'),
    ]

    operations = [
        migrations.RunPython(avanti, migrations.RunPython.noop),
    ]
