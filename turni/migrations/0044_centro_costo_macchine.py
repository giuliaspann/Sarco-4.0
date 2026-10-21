"""Centro di costo sulle macchine, dalla proposta "Mezzi e attrezzature" (settembre 2026).

Codice = targa o matricola, come nella 0043. Vuoto dove la proposta non ha deciso
(mulini a martelli e separatore aeraulico: Sabbia o Metalli): si sceglie dalla scheda della macchina.
"""

from django.db import migrations, models

# codice, centro di costo
CENTRI = [
    ('230', 'PIAZZALE'),
    ('CJ958XY', 'GENERALI'),
    ('AX673XX', 'GENERALI'),
    ('DP028HW', 'GENERALI'),
    ('CL689NW', 'TRASPORTI'),
    ('GE091JV', 'TRASPORTI'),
    ('PC015805', 'TRASPORTI'),
    ('GY056ST', 'TRASPORTI'),
    ('FH042MW', 'TRASPORTI'),
    ('XB601BV', 'TRASPORTI'),
    ('GG133HR', 'TRASPORTI'),
    ('FM195NE', 'GENERALI'),
    ('GJ455YN', 'GENERALI'),
    ('A5020035', 'METALLI'),
    ('B16006G02604', 'PIAZZALE'),
    ('B16006G02643', 'PIAZZALE'),
    ('FN729214', 'PIAZZALE'),
    ('FN729188', 'PIAZZALE'),
    ('FN740588', 'PIAZZALE'),
    ('A276B12525U', 'PIAZZALE'),
    ('A276B12526U', 'PIAZZALE'),
    ('LGPK013', 'PIAZZALE'),
    ('15209', 'GENERALI'),
    ('GHLR150FOE195815', 'PIAZZALE'),
    ('9020063', 'GENERALI'),
    ('1566.307', 'SABBIA'),
    ('M1', 'SABBIA'),
    ('28', ''),
    ('260264', ''),
    ('520170', 'PIAZZALE'),
    ('16108', 'PIAZZALE'),
    ('3377', 'PIAZZALE'),
    ('15634', 'PIAZZALE'),
    ('17236', 'PIAZZALE'),
    ('HFLNUD50C00500142', 'PIAZZALE'),
    ('682008', 'METALLI'),
    ('48-482490/2', 'IMP1'),
    ('XA139AV', 'TRASPORTI'),
    ('AB85608', 'TRASPORTI'),
    ('AB39594', 'TRASPORTI'),
    ('XB225AF', 'TRASPORTI'),
    ('XA638MZ', 'TRASPORTI'),
    ('XA067LA', 'TRASPORTI'),
    ('AA27672', 'TRASPORTI'),
    ('XA655BY', 'TRASPORTI'),
    ('XA876WK', 'TRASPORTI'),
    ('AO03915', 'TRASPORTI'),
    ('AA32214', 'TRASPORTI'),
    ('XA431ZX', 'TRASP_USC'),
    ('XA905ZL', 'TRASP_USC'),
    ('XA906ZL', 'TRASP_USC'),
    ('XA941ZL', 'TRASP_USC'),
    ('XA942ZL', 'TRASP_USC'),
    ('260265', ''),
    ('EM824SK', 'TRASPORTI'),
    ('EF063JH', 'TRASPORTI'),
    ('XX0126', 'IMP1'),
    ('22-2265', 'METALLI'),
    ('909001', 'IMP1'),
    ('SZBMPB100H3X00068', 'IMP1'),
    ('XX0111', 'IMP1'),
]


def carica(apps, schema_editor):
    Macchina = apps.get_model('turni', 'Macchina')
    for codice, centro in CENTRI:
        Macchina.objects.filter(codice=codice, centro_costo='').update(centro_costo=centro)


class Migration(migrations.Migration):
    dependencies = [('turni', '0043_elenco_attrezzature_mezzi')]
    operations = [
        migrations.AddField(
            model_name='macchina',
            name='centro_costo',
            field=models.CharField(blank=True, choices=[('IMP1', 'Impianto 1'), ('IMP2', 'Impianto 2'), ('SABBIA', 'Sabbia (Superbi)'), ('METALLI', 'Metalli'), ('TRASPORTI', 'Trasporti'), ('TRASP_ENT', 'Trasporti in entrata'), ('TRASP_USC', 'Trasporti in uscita'), ('PIAZZALE', 'Piazzale'), ('GENERALI', 'Generali')], max_length=10, verbose_name='centro di costo'),
        ),
        migrations.RunPython(carica, migrations.RunPython.noop),
    ]
