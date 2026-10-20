"""Era una prova: creava una "Pulizia Pala" per Spanò Giulia dal 19 al 21 ottobre 2026.
Svuotata perché i dati di prova non finiscano in un database nuovo; il file resta per la catena
delle migrazioni (la 0037 dipende da questa). Sul database reale era già stata applicata."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('turni', '0035_foto_prima')]
    operations = []
