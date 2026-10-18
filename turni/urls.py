from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views, views_manutenzione, views_messaggi, views_richieste

app_name = 'turni'

urlpatterns = [
    path('', views.home, name='home'),
    path('accesso/', views.Accesso.as_view(), name='login'),
    path('esci/', LogoutView.as_view(), name='logout'),
    path('miei/', views.miei_turni, name='miei_turni'),
    path('squadra/', views.squadra, name='squadra'),
    path('settimana/', views.settimana_tutti, name='settimana_tutti'),
    path('pulizie/', views.pulizie, name='pulizie'),
    path('pulizie/<int:turno_id>/', views.pulizie, name='pulizie_turno'),
    path('capoturno/', views.capoturno, name='capoturno'),
    path('foto/<int:pulizia_id>/', views.foto, name='foto'),
    path('richieste/', views_richieste.richieste, name='richieste'),
    path('richieste/cambio/', views_richieste.nuovo_cambio, name='nuovo_cambio'),
    path('richieste/ferie/', views_richieste.nuove_ferie, name='nuove_ferie'),
    path('richieste/avviso/', views_richieste.nuovo_avviso, name='nuovo_avviso'),
    path('extra/<int:extra_id>/', views_richieste.rispondi_extra, name='rispondi_extra'),
    path('ufficio/extra/', views_richieste.ufficio_extra, name='ufficio_extra'),
    path('messaggi/', views_messaggi.messaggi, name='messaggi'),
    path('messaggi/chat/nuovi/', views_messaggi.chat_nuovi, name='chat_nuovi'),
    path('notifiche/iscrivi/', views_messaggi.iscrivi_notifiche, name='iscrivi_notifiche'),
    path('manutenzione/', views_manutenzione.manutenzione, name='manutenzione'),
    path('manutenzione/interventi/', views_manutenzione.interventi, name='interventi'),
    path('manutenzione/fermi/', views_manutenzione.fermi, name='fermi'),
    path('manutenzione/fermi/nuovo/', views_manutenzione.nuovo_fermo, name='nuovo_fermo'),
    path('manutenzione/fermi/<int:fermo_id>/', views_manutenzione.fermo, name='fermo'),
    path('manutenzione/fermi/<int:fermo_id>/foto/<str:quale>/', views_manutenzione.foto_fermo, name='foto_fermo'),
    path('manutenzione/segnala/', views_manutenzione.segnala, name='segnala'),
    path('manutenzione/interventi/<int:intervento_id>/', views_manutenzione.intervento, name='intervento'),
    path('manutenzione/macchine/', views_manutenzione.macchine, name='macchine'),
    path('manutenzione/macchine/<int:macchina_id>/', views_manutenzione.macchina, name='macchina'),
    path('manutenzione/ricambi/', views_manutenzione.ricambi, name='ricambi'),
    path('manutenzione/ordini/', views_manutenzione.ordini, name='ordini'),
    path('manutenzione/ordini/nuovo/', views_manutenzione.nuovo_ordine, name='nuovo_ordine'),
    path('manutenzione/programmate/', views_manutenzione.programmate, name='programmate'),
    path('manutenzione/etichette/', views_manutenzione.etichette, name='etichette'),
    path('manutenzione/foto/<str:tipo>/<int:oggetto_id>/', views_manutenzione.foto, name='foto_mn'),
    path('ufficio/richieste/', views_richieste.ufficio_richieste, name='ufficio_richieste'),
    path('ufficio/importa/', views.importa_turni, name='importa'),
    path('ufficio/importa/anteprima/', views.anteprima, name='anteprima'),
    path('ufficio/dipendenti/', views.dipendenti, name='dipendenti'),
    path('ufficio/credenziali/', views.credenziali, name='credenziali'),
]
