"""Era una prova: riportava "da completare" la "Pulizia Pala" di Spanò Giulia (19-21 ottobre 2026).
Svuotata perché i dati di prova non finiscano in un database nuovo; il file resta per la catena
delle migrazioni. Sul database reale era già stata applicata."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('turni', '0041_nome_segnaletica')]
    operations = []
