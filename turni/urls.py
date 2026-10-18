from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views, views_richieste

app_name = 'turni'

urlpatterns = [
    path('', views.home, name='home'),
    path('accesso/', views.Accesso.as_view(), name='login'),
    path('esci/', LogoutView.as_view(), name='logout'),
    path('miei/', views.miei_turni, name='miei_turni'),
    path('squadra/', views.squadra, name='squadra'),
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
    path('ufficio/richieste/', views_richieste.ufficio_richieste, name='ufficio_richieste'),
    path('ufficio/importa/', views.importa_turni, name='importa'),
    path('ufficio/importa/anteprima/', views.anteprima, name='anteprima'),
    path('ufficio/dipendenti/', views.dipendenti, name='dipendenti'),
]
