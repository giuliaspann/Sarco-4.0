"""Il Responsabile Impianto ha le stesse funzioni dell'ufficio: pagine dell'ufficio (is_staff) e richieste
da approvare (Giulia, 25/11/2026)."""

from django.db import migrations


def avanti(apps, schema_editor):
    Dipendente = apps.get_model('turni', 'Dipendente')
    Permission = apps.get_model('auth', 'Permission')
    perm = Permission.objects.filter(codename='approva_richieste', content_type__app_label='turni').first()
    for dip in Dipendente.objects.filter(resp_impianto=True, utente__isnull=False).select_related('utente'):
        u = dip.utente
        if u.is_superuser:
            continue
        if not u.is_staff:
            u.is_staff = True
            u.save(update_fields=['is_staff'])
        if perm is not None:
            u.user_permissions.add(perm)


class Migration(migrations.Migration):
    dependencies = [('turni', '0089_ufficio_stesse_funzioni')]

    operations = [migrations.RunPython(avanti, migrations.RunPython.noop)]
