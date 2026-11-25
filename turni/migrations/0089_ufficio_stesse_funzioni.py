"""Tutti i dipendenti dell'ufficio (HR / ufficio turni, Direzione, Amministrazione) hanno le stesse funzioni
del profilo «ufficio»: pagine dell'ufficio (is_staff) e richieste da approvare (Giulia, 25/11/2026)."""

from django.db import migrations

UFFICI = ('RESP_TURNI', 'DIREZIONE', 'AMMINIS')


def avanti(apps, schema_editor):
    Dipendente = apps.get_model('turni', 'Dipendente')
    Permission = apps.get_model('auth', 'Permission')
    perm = Permission.objects.filter(codename='approva_richieste', content_type__app_label='turni').first()
    for dip in Dipendente.objects.filter(ruolo_app__in=UFFICI, utente__isnull=False).select_related('utente'):
        u = dip.utente
        if u.is_superuser:
            continue
        if not u.is_staff:
            u.is_staff = True
            u.save(update_fields=['is_staff'])
        if perm is not None:
            u.user_permissions.add(perm)


class Migration(migrations.Migration):
    dependencies = [
        ('turni', '0088_extra_capoturno'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [migrations.RunPython(avanti, migrations.RunPython.noop)]
