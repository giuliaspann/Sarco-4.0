from django.contrib import admin

from .models import Dipendente, ElementoPulizia, NotaSettimana, Pulizia, RegolaPulizia, Settimana, Turno

admin.site.site_header = 'Sarco 4.0'


class RegolaInline(admin.TabularInline):
    model = RegolaPulizia
    extra = 1
    verbose_name = 'chi lo pulisce'
    verbose_name_plural = 'chi lo pulisce (una riga per ogni ruolo)'


@admin.register(ElementoPulizia)
class ElementoPuliziaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'tipo', 'attivo']
    list_filter = ['tipo', 'attivo']
    inlines = [RegolaInline]


@admin.register(RegolaPulizia)
class RegolaPuliziaAdmin(admin.ModelAdmin):
    list_display = ['elemento', 'postazione', 'fascia', 'solo_capoturno']
    list_filter = ['postazione', 'fascia', 'solo_capoturno']


@admin.register(Dipendente)
class DipendenteAdmin(admin.ModelAdmin):
    list_display = ['nome', 'utente', 'attivo', 'tutor']
    list_filter = ['attivo']
    search_fields = ['nome']


class NotaInline(admin.TabularInline):
    model = NotaSettimana
    extra = 0


@admin.register(Settimana)
class SettimanaAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'foglio', 'pubblicata', 'caricata_il', 'caricata_da']
    inlines = [NotaInline]


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display = ['data', 'dipendente', 'codice', 'fascia', 'postazione', 'capoturno']
    list_filter = ['settimana', 'fascia', 'postazione', 'capoturno']
    search_fields = ['dipendente__nome']
    date_hierarchy = 'data'


@admin.register(Pulizia)
class PuliziaAdmin(admin.ModelAdmin):
    list_display = ['turno', 'elemento', 'stato', 'fatta_il', 'verificata_da']
    list_filter = ['stato', 'elemento', 'turno__data']
    search_fields = ['turno__dipendente__nome']
