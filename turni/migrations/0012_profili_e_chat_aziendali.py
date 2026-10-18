"""Profili dall'organigramma, chat aziendali e messaggi già scritti nella chat Turni."""

from django.db import migrations


def applica(apps, schema_editor):
    from turni.organigramma import CHAT, PROFILI, QUALIFICHE

    Dipendente = apps.get_model('turni', 'Dipendente')
    Chat = apps.get_model('turni', 'Chat')
    MessaggioChat = apps.get_model('turni', 'MessaggioChat')
    StatoMessaggi = apps.get_model('turni', 'StatoMessaggi')
    LetturaChat = apps.get_model('turni', 'LetturaChat')

    for nome, qualifica, ruolo in PROFILI:
        d, _ = Dipendente.objects.get_or_create(nome=nome, defaults={'mansione': 'UFFICIO'})
        d.qualifica, d.ruolo_app = qualifica, ruolo
        d.save(update_fields=['qualifica', 'ruolo_app'])
    for nome, qualifica in QUALIFICHE.items():
        Dipendente.objects.filter(nome=nome, qualifica='').update(qualifica=qualifica)

    chat = {}
    for i, (nome, emoji) in enumerate(CHAT):
        chat[nome], _ = Chat.objects.get_or_create(nome=nome, defaults={'emoji': emoji, 'ordine': i})
    # i messaggi scritti finora erano tutti nella chat unica: diventano la chat Turni
    MessaggioChat.objects.filter(chat__isnull=True).update(chat=chat['Turni'])
    for s in StatoMessaggi.objects.filter(chat_letta_fino__gt=0):
        LetturaChat.objects.get_or_create(utente_id=s.utente_id, chat=chat['Turni'], defaults={'letta_fino': s.chat_letta_fino})


class Migration(migrations.Migration):
    dependencies = [('turni', '0011_ruoli_e_chat')]
    operations = [migrations.RunPython(applica, migrations.RunPython.noop)]
