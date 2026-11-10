from django.contrib import admin

from .models import CambioTurno, Dipendente, RichiestaFerie, ElementoPulizia, NotaSettimana, Pulizia, RegolaPulizia, Settimana, Turno

from django.contrib.admin.forms import AdminAuthenticationForm

from .sicurezza import ProtezioneAccesso


class AdminAccessoForm(ProtezioneAccesso, AdminAuthenticationForm):
    pass


admin.site.site_header = 'Sarco 4.0'
admin.site.login_form = AdminAccessoForm


class RegolaInline(admin.TabularInline):
    model = RegolaPulizia
    extra = 1
    verbose_name = 'chi lo pulisce'
    verbose_name_plural = 'chi lo pulisce (una riga per ogni ruolo)'


@admin.register(ElementoPulizia)
class ElementoPuliziaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'tipo', 'modo', 'convalida', 'minuti_prima_fine', 'attivo']
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


@admin.register(CambioTurno)
class CambioTurnoAdmin(admin.ModelAdmin):
    list_display = ['richiedente', 'collega', 'giorno1', 'giorno2', 'stato', 'creato_il', 'gestito_da']
    list_filter = ['stato']
    search_fields = ['richiedente__nome', 'collega__nome']


@admin.register(RichiestaFerie)
class RichiestaFerieAdmin(admin.ModelAdmin):
    list_display = ['dipendente', 'tipo', 'dal', 'al', 'stato', 'creata_il', 'gestita_da']
    list_filter = ['stato', 'tipo']
    search_fields = ['dipendente__nome']


from .models import FotoIntervento, Intervento, Macchina, ManutenzioneProgrammata, OrdineRicambio, Ricambio, RicambioUsato  # noqa: E402


@admin.register(Macchina)
class MacchinaAdmin(admin.ModelAdmin):
    list_display = ['nome', 'codice', 'luogo', 'tipo', 'categoria', 'marca', 'modello', 'attiva', 'esempio']
    list_filter = ['luogo', 'tipo', 'attiva', 'esempio']
    search_fields = ['nome', 'codice', 'marca', 'matricola']


@admin.register(Ricambio)
class RicambioAdmin(admin.ModelAdmin):
    list_display = ['nome', 'codice', 'scorta', 'scorta_minima', 'unita', 'ubicazione', 'fornitore']
    search_fields = ['nome', 'codice']
    filter_horizontal = ['macchine']


class RicambioUsatoInline(admin.TabularInline):
    model = RicambioUsato
    extra = 0
    verbose_name_plural = 'pezzi usati (il costo si copia dal magazzino, si può correggere)'


class FotoInterventoInline(admin.TabularInline):
    model = FotoIntervento
    extra = 0


@admin.register(Intervento)
class InterventoAdmin(admin.ModelAdmin):
    list_display = ['pk', 'macchina', 'tipo', 'stato', 'priorita', 'macchina_ferma', 'assegnata_a', 'segnalata_il', 'costo_esterno']
    list_filter = ['stato', 'tipo', 'macchina__luogo']
    search_fields = ['descrizione', 'lavoro_svolto', 'macchina__nome']
    inlines = [RicambioUsatoInline, FotoInterventoInline]


@admin.register(OrdineRicambio)
class OrdineRicambioAdmin(admin.ModelAdmin):
    list_display = ['numero', 'ricambio', 'descrizione', 'quantita', 'stato', 'urgente', 'richiesto_il', 'fornitore']
    list_filter = ['stato']
    search_fields = ['descrizione', 'ricambio__nome', 'fornitore']


admin.site.register(ManutenzioneProgrammata)


from .models import (  # noqa: E402
    AnalisiProdotto, Annuncio, AvvisoAssenza, Comunicazione, Disponibilita, EventoIntervento, FermoImpianto, FotoComunicazione,
    FotoIntervento, ModificaTurno, ProdottoProduzione, ProduzioneTurno, RicambioUsato, RigaProduzione, RispostaComunicazione,
    PuliziaGenerale, SaldoFerie, TurnoExtra,
)


@admin.register(ProdottoProduzione)
class ProdottoProduzioneAdmin(admin.ModelAdmin):
    list_display = ['codice', 'nome', 'impianto', 'categoria', 'ordine', 'attivo']
    list_editable = ['categoria', 'ordine', 'attivo']


class RigaProduzioneInline(admin.TabularInline):
    model = RigaProduzione
    extra = 0


@admin.register(ProduzioneTurno)
class ProduzioneTurnoAdmin(admin.ModelAdmin):
    list_display = ['data', 'fascia', 'inserita_da', 'inserita_il']
    list_filter = ['fascia']
    date_hierarchy = 'data'
    inlines = [RigaProduzioneInline]


# tutti gli altri dati inseriti dall'app: l'amministratore li può correggere da qui.
# Restano fuori di proposito le chat private, le iscrizioni alle notifiche e i blocchi d'accesso.
for modello, colonne in [
    (NotaSettimana, None), (PuliziaGenerale, ['data', 'esito', 'deciso_da', 'deciso_il']), (ModificaTurno, None), (SaldoFerie, ['dipendente', 'al', 'ferie_ore', 'rol_ore']),
    (TurnoExtra, ['data', 'fascia', 'postazione', 'posti', 'chiusa']), (Disponibilita, ['extra', 'dipendente', 'confermata']),
    (AvvisoAssenza, ['dipendente', 'data', 'tipo']), (Annuncio, None),
    (EventoIntervento, None), (FermoImpianto, ['impianto', 'causa', 'fermo_dal', 'ripartito_il', 'segnalato_da']),
    (Comunicazione, None), (FotoComunicazione, None), (RispostaComunicazione, None),
    (AnalisiProdotto, ['data', 'fascia', 'campione', 'inserita_da']),
]:
    admin.site.register(modello, type(f'{modello.__name__}Admin', (admin.ModelAdmin,), {'list_display': colonne or ['__str__']}))
