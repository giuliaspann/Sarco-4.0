from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

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
    path('ufficio/importa/', views.importa_turni, name='importa'),
    path('ufficio/importa/anteprima/', views.anteprima, name='anteprima'),
    path('ufficio/dipendenti/', views.dipendenti, name='dipendenti'),
]
