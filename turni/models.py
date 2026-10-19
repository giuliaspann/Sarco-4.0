from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Fascia(models.TextChoices):
    MATTINA = '1T', '1° turno'
    POMERIGGIO = '2T', '2° turno'
    NOTTE = 'N', 'Notturno'
    GIORNALIERO = 'G', 'Giornaliero'
    RIPOSO = 'RIP', 'Riposo'
    FERIE = 'FERIE', 'Ferie'
    FESTA = 'FESTA', 'Festa'
    PERMESSO = 'CP', 'Congedo / permesso'
    ALTRO = 'ALTRO', 'Altro'


# Fasce in cui la persona lavora (e quindi ha pulizie a fine turno)
FASCE_LAVORATIVE = {Fascia.MATTINA, Fascia.POMERIGGIO, Fascia.NOTTE, Fascia.GIORNALIERO, Fascia.ALTRO}


class Postazione(models.TextChoices):
    IMP1 = 'IMP1', 'Impianto 1'
    IMP2 = 'IMP2', 'Impianto 2'
    ANALISI = 'ANALISI', 'Analisi'
    SUPERBI = 'SUPERBI', 'Superbi'
    MULINO = 'MULINO', 'Mulino'
    BARROTTI = 'BARROTTI', 'Barrotti'
    PALISTA = 'PALISTA', 'Palista'
    METALLI = 'METALLI', 'Metalli'
    SABBIA = 'SABBIA', 'Sabbia'
    PIAZZALE = 'PIAZZALE', 'Piazzale'
    AUTISTA = 'AUTISTA', 'Autista'
    MANUT = 'MANUT', 'Manutentore'
    UFFICIO = 'UFFICIO', 'Ufficio'


# Orari dei turni (dal foglio dell'ufficio)
ORARI = {
    Fascia.MATTINA: '06:00–14:00',
    Fascia.POMERIGGIO: '14:00–22:00',
    Fascia.GIORNALIERO: '08:00–13:00 · 14:30–17:30',
    Fascia.NOTTE: '22:00–06:00',
}

# Le pulizie si fanno negli ultimi 30 minuti del turno (il giornaliero a fine giornata)
ORARI_PULIZIE = {
    Fascia.MATTINA: '13:30–14:00',
    Fascia.POMERIGGIO: '21:30–22:00',
    Fascia.GIORNALIERO: '17:00–17:30',
    Fascia.NOTTE: '05:30–06:00',
}


class Mansione(models.TextChoices):
    OPERAIO = 'OPERAIO', 'Operaio'
    MANUTENTORE = 'MANUTENTORE', 'Manutentore'
    PALISTA = 'PALISTA', 'Palista'
    AUTISTA = 'AUTISTA', 'Autista'
    PIAZZALE = 'PIAZZALE', 'Piazzale'
    UFFICIO = 'UFFICIO', 'Ufficio'


class RuoloApp(models.TextChoices):
    OPERAIO = 'OPERAIO', 'Dipendente'
    DIREZIONE = 'DIREZIONE', 'Direzione'
    RESP_TURNI = 'RESP_TURNI', 'Responsabile turni'


class Dipendente(models.Model):
    nome = models.CharField('nome come nel file turni', max_length=100, unique=True)
    utente = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='dipendente'
    )
    attivo = models.BooleanField(default=True)
    tutor = models.CharField('tutor (apprendisti)', max_length=200, blank=True)
    # Il file turni non la dice: la imposta l'ufficio (serve per cercare manutentori o palisti)
    # una o più, separate da virgola (es. "OPERAIO,PALISTA")
    mansione = models.CharField(max_length=80, default=Mansione.OPERAIO)
    # cosa può fare nell'app: la direzione è in tutte le chat e ne vede lo storico completo,
    # il responsabile turni ha le pagine dell'ufficio
    ruolo_app = models.CharField('ruolo nell\'app', max_length=12, choices=RuoloApp.choices, default=RuoloApp.OPERAIO)
    qualifica = models.CharField('ruolo in azienda', max_length=150, blank=True)
    # incarichi per la manutenzione
    resp_manutenzione = models.BooleanField('responsabile manutenzione', default=False)
    acquisti = models.BooleanField('ordina i ricambi (acquisti)', default=False)
    # Il PIN è corto: dopo troppi tentativi sbagliati l'accesso si blocca per un po'
    tentativi_falliti = models.PositiveSmallIntegerField(default=0, editable=False)
    bloccato_fino = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name_plural = 'dipendenti'
        ordering = ['nome']

    def __str__(self):
        return self.nome

    @property
    def mansioni(self):
        return [m for m in self.mansione.split(',') if m]

    @property
    def mansioni_display(self):
        nomi = dict(Mansione.choices)
        return ' e '.join(nomi.get(m, m) for m in self.mansioni)

    @property
    def nome_breve(self):
        return self.nome.title().replace("'", "’")


class Settimana(models.Model):
    lunedi = models.DateField(unique=True)
    file_originale = models.CharField(max_length=255, blank=True)
    foglio = models.CharField(max_length=50, blank=True)
    caricata_il = models.DateTimeField(auto_now=True)
    caricata_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    pubblicata = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = 'settimane'
        ordering = ['-lunedi']

    def __str__(self):
        return f'Dal {self.lunedi:%d/%m/%Y} al {self.domenica:%d/%m/%Y}'

    @property
    def domenica(self):
        return self.lunedi + timedelta(days=6)

    @property
    def giorni(self):
        return [self.lunedi + timedelta(days=i) for i in range(7)]


class NotaSettimana(models.Model):
    """Le righe a lato della tabella: ferie, richieste, promemoria."""

    settimana = models.ForeignKey(Settimana, on_delete=models.CASCADE, related_name='note')
    riferimento = models.CharField('settimana n.', max_length=50, blank=True)
    dipendente = models.CharField(max_length=100, blank=True)
    testo = models.CharField(max_length=500)
    ordine = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['ordine']

    def __str__(self):
        return f'{self.dipendente}: {self.testo}'


class Turno(models.Model):
    settimana = models.ForeignKey(Settimana, on_delete=models.CASCADE, related_name='turni')
    dipendente = models.ForeignKey(Dipendente, on_delete=models.CASCADE, related_name='turni')
    data = models.DateField()
    codice = models.CharField('codice originale', max_length=60, blank=True)
    fascia = models.CharField(max_length=10, choices=Fascia.choices)
    postazione = models.CharField(max_length=10, choices=Postazione.choices, blank=True)
    capoturno = models.BooleanField(default=False)
    # Cambiato dall'app (cambio turno o ferie approvati): ricaricando l'Excel non viene sovrascritto
    nota_modifica = models.CharField(max_length=200, blank=True)

    class Meta:
        verbose_name_plural = 'turni'
        ordering = ['data', 'dipendente__nome']
        constraints = [models.UniqueConstraint(fields=['dipendente', 'data'], name='un_turno_al_giorno')]

    def __str__(self):
        return f'{self.dipendente} {self.data:%d/%m} {self.descrizione}'

    @property
    def lavora(self):
        return self.fascia in FASCE_LAVORATIVE

    @property
    def descrizione(self):
        if not self.lavora:
            return self.get_fascia_display()
        parti = []
        if self.capoturno:
            parti.append('Capo turno')
        if self.fascia != Fascia.ALTRO:
            parti.append(self.get_fascia_display())
        if self.postazione:
            parti.append(self.get_postazione_display())
        return ' · '.join(parti) or self.codice

    @property
    def descrizione_fascia(self):
        """Solo il turno (senza postazione): l'impianto va nel suo riquadro a parte."""
        if not self.lavora:
            return self.get_fascia_display()
        parti = []
        if self.capoturno:
            parti.append('Capo turno')
        if self.fascia != Fascia.ALTRO:
            parti.append(self.get_fascia_display())
        elif self.capoturno:
            parti.append('turno da indicare')
        return ' · '.join(parti) or self.codice

    # il file a volte scrive solo "CAPO T. - Imp. 1": la fascia la indica poi il capo turno o l'ufficio
    SIGLE_CAPO = {Fascia.MATTINA: 'CT1', Fascia.POMERIGGIO: 'CT2', Fascia.NOTTE: 'CTN', Fascia.GIORNALIERO: 'CTG'}

    @property
    def capo_da_completare(self):
        return self.capoturno and self.fascia == Fascia.ALTRO

    @property
    def nome_postazione(self):
        return self.get_postazione_display() if self.lavora and self.postazione else ''

    @property
    def orario(self):
        return ORARI.get(self.fascia, '') if self.lavora else ''

    @property
    def orario_pulizie(self):
        return ORARI_PULIZIE.get(self.fascia, '') if self.lavora else ''

    SIGLE = {
        Fascia.MATTINA: '1T',
        Fascia.POMERIGGIO: '2T',
        Fascia.NOTTE: 'N',
        Fascia.GIORNALIERO: 'G',
        Fascia.RIPOSO: 'R',
        Fascia.FERIE: 'F',
        Fascia.FESTA: 'FS',
        Fascia.PERMESSO: 'P',
        Fascia.ALTRO: 'CT',
    }

    @property
    def sigla(self):
        """Sigla corta per la casella del calendario. Capo turno: CT1, CT2, CTN (CT? se manca la fascia)."""
        if self.capoturno and self.lavora:
            return self.SIGLE_CAPO.get(self.fascia, 'CT?')
        return self.SIGLE.get(self.fascia, '?')

    SIGLE_POSTAZIONE = {
        Postazione.METALLI: 'MET.',
        Postazione.SABBIA: 'SABB.',
        Postazione.PIAZZALE: 'PIAZ.',
        Postazione.AUTISTA: 'AUT.',
        Postazione.MANUT: 'MAN.',
        Postazione.UFFICIO: 'UFF.',
        Postazione.IMP1: 'IMP 1',
        Postazione.IMP2: 'IMP 2',
        Postazione.ANALISI: 'ANAL.',
        Postazione.SUPERBI: 'SUP.',
        Postazione.MULINO: 'MUL.',
        Postazione.BARROTTI: 'BARR.',
        Postazione.PALISTA: 'PALA',
    }

    @property
    def sigla_postazione(self):
        """Seconda casellina del calendario: dove si lavora, abbreviato per stare nella cella."""
        return self.SIGLE_POSTAZIONE.get(self.postazione, '') if self.lavora else ''

    @property
    def classe_fascia(self):
        """Colore della casella del calendario: dipende solo dalla fascia, per leggerlo a colpo d'occhio."""
        if self.capoturno and self.lavora:
            return 'f-capo'
        return {
            Fascia.MATTINA: 'f-mattina',
            Fascia.POMERIGGIO: 'f-pomeriggio',
            Fascia.NOTTE: 'f-notte',
            Fascia.GIORNALIERO: 'f-giorno',
            Fascia.ALTRO: 'f-capo',
            Fascia.FERIE: 'f-ferie',
            Fascia.PERMESSO: 'f-ferie',
        }.get(self.fascia, 'f-riposo')

    @property
    def colore(self):
        """Classe CSS che richiama i colori dell'Excel."""
        if not self.lavora:
            return 'off'
        if self.fascia == Fascia.NOTTE:
            return 'notte'
        if self.postazione == Postazione.IMP1:
            return 'imp1'
        if self.postazione == Postazione.IMP2:
            return 'imp2'
        return 'altro'


# ---------------------------------------------------------------- Pulizie


class ElementoPulizia(models.Model):
    class Tipo(models.TextChoices):
        MEZZO = 'MEZZO', 'Mezzo'
        ZONA = 'ZONA', "Zona dell'impianto"

    nome = models.CharField(max_length=100, unique=True)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    istruzioni = models.TextField(blank=True, help_text="Cosa pulire e come: lo vede l'operaio nella checklist")
    attivo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'mezzo / zona da pulire'
        verbose_name_plural = 'mezzi e zone da pulire'
        ordering = ['tipo', 'nome']

    def __str__(self):
        return self.nome


class RegolaPulizia(models.Model):
    """Chi deve pulire cosa: si applica ai turni che corrispondono a tutti i campi compilati."""

    elemento = models.ForeignKey(ElementoPulizia, on_delete=models.CASCADE, related_name='regole')
    postazione = models.CharField(max_length=10, choices=Postazione.choices, blank=True, help_text='vuoto = tutte')
    fascia = models.CharField(
        max_length=10,
        choices=[(f.value, f.label) for f in Fascia if f in FASCE_LAVORATIVE],
        blank=True,
        help_text='vuoto = tutte',
    )
    solo_capoturno = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'regola pulizia'
        verbose_name_plural = 'regole pulizie'

    def __str__(self):
        chi = ' '.join(
            filter(
                None,
                [
                    'Capo turno' if self.solo_capoturno else '',
                    self.get_fascia_display() if self.fascia else '',
                    self.get_postazione_display() if self.postazione else 'tutte le postazioni',
                ],
            )
        )
        return f'{chi} → {self.elemento}'

    def si_applica(self, turno):
        return (
            (not self.postazione or self.postazione == turno.postazione)
            and (not self.fascia or self.fascia == turno.fascia)
            and (not self.solo_capoturno or turno.capoturno)
        )


def percorso_foto(istanza, nome):
    return f'pulizie/{istanza.turno.data:%Y/%m}/{istanza.turno_id}-{istanza.elemento_id}-{timezone.now():%H%M%S}.jpg'


class Pulizia(models.Model):
    class Stato(models.TextChoices):
        DA_FARE = 'DA_FARE', 'Da fare'
        FATTA = 'FATTA', 'Fatta'
        VERIFICATA = 'VERIFICATA', 'Verificata'
        SEGNALATA = 'SEGNALATA', 'Da rifare'

    turno = models.ForeignKey(Turno, on_delete=models.CASCADE, related_name='pulizie')
    elemento = models.ForeignKey(ElementoPulizia, on_delete=models.PROTECT)
    aggiunta_da_operaio = models.BooleanField(default=False, help_text='mezzo usato aggiunto a mano')
    stato = models.CharField(max_length=12, choices=Stato.choices, default=Stato.DA_FARE)
    fatta_il = models.DateTimeField(null=True, blank=True)
    foto = models.ImageField(upload_to=percorso_foto, blank=True)
    nota = models.CharField(max_length=300, blank=True)
    verificata_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    verificata_il = models.DateTimeField(null=True, blank=True)
    nota_verifica = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name_plural = 'pulizie'
        ordering = ['elemento__tipo', 'elemento__nome']
        constraints = [models.UniqueConstraint(fields=['turno', 'elemento'], name='una_pulizia_per_elemento')]

    def __str__(self):
        return f'{self.turno} — {self.elemento} ({self.get_stato_display()})'


# ---------------------------------------------------------------- Richieste


class CambioTurno(models.Model):
    """Due colleghi si scambiano il turno in uno o due giorni.

    Esempio "lavoro contro riposo": il giorno 1 lavora il richiedente e riposa il collega,
    il giorno 2 il contrario; dopo il cambio è tutto invertito. Con un giorno solo si
    scambiano due turni dello stesso giorno (es. 1° turno con 2° turno).
    Lo accetta prima il collega, poi lo approva il responsabile turni.
    """

    class Stato(models.TextChoices):
        ATTESA_COLLEGA = 'ATTESA_COLLEGA', 'In attesa del collega'
        ATTESA_UFFICIO = 'ATTESA_UFFICIO', "In attesa dell'ufficio"
        APPROVATO = 'APPROVATO', 'Approvato'
        RIFIUTATO_COLLEGA = 'RIFIUTATO_COLLEGA', 'Rifiutato dal collega'
        RIFIUTATO_UFFICIO = 'RIFIUTATO_UFFICIO', "Rifiutato dall'ufficio"
        ANNULLATO = 'ANNULLATO', 'Annullato'

    IN_CORSO = (Stato.ATTESA_COLLEGA, Stato.ATTESA_UFFICIO)

    richiedente = models.ForeignKey(Dipendente, on_delete=models.CASCADE, related_name='cambi_chiesti')
    collega = models.ForeignKey(Dipendente, on_delete=models.CASCADE, related_name='cambi_ricevuti')
    giorno1 = models.DateField('giorno')
    giorno2 = models.DateField('giorno di recupero', null=True, blank=True)
    # I turni com'erano al momento della richiesta: se nel frattempo cambiano, il cambio non si applica
    situazione = models.JSONField(default=dict, editable=False)
    motivo = models.CharField(max_length=300, blank=True)
    stato = models.CharField(max_length=20, choices=Stato.choices, default=Stato.ATTESA_COLLEGA)
    creato_il = models.DateTimeField(auto_now_add=True)
    risposta_collega_il = models.DateTimeField(null=True, blank=True)
    gestito_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    gestito_il = models.DateTimeField(null=True, blank=True)
    nota_ufficio = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = 'cambio turno'
        verbose_name_plural = 'cambi turno'
        ordering = ['-creato_il']
        permissions = [('approva_richieste', 'Può approvare cambi turno e ferie')]

    def __str__(self):
        return f'{self.richiedente} ↔ {self.collega} {self.giorno1:%d/%m}'

    @property
    def giorni(self):
        return [g for g in (self.giorno1, self.giorno2) if g]

    @property
    def in_corso(self):
        return self.stato in self.IN_CORSO

    @property
    def scaduto(self):
        return self.in_corso and self.giorno1 <= timezone.localdate()


class RichiestaFerie(models.Model):
    class Tipo(models.TextChoices):
        FERIE = 'FERIE', 'Ferie'
        PERMESSO = 'PERMESSO', 'Permesso'

    class Stato(models.TextChoices):
        ATTESA = 'ATTESA', "In attesa dell'ufficio"
        APPROVATA = 'APPROVATA', 'Approvata'
        RIFIUTATA = 'RIFIUTATA', 'Rifiutata'
        ANNULLATA = 'ANNULLATA', 'Annullata'

    dipendente = models.ForeignKey(Dipendente, on_delete=models.CASCADE, related_name='richieste_ferie')
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.FERIE)
    dal = models.DateField()
    al = models.DateField()
    motivo = models.CharField(max_length=300, blank=True)
    stato = models.CharField(max_length=10, choices=Stato.choices, default=Stato.ATTESA)
    creata_il = models.DateTimeField(auto_now_add=True)
    gestita_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    gestita_il = models.DateTimeField(null=True, blank=True)
    nota_ufficio = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = 'richiesta ferie'
        verbose_name_plural = 'richieste ferie'
        ordering = ['-creata_il']

    def __str__(self):
        return f'{self.dipendente} {self.get_tipo_display()} {self.dal:%d/%m}–{self.al:%d/%m}'

    @property
    def giorni(self):
        return (self.al - self.dal).days + 1

    @property
    def fascia(self):
        return Fascia.FERIE if self.tipo == self.Tipo.FERIE else Fascia.PERMESSO


class TurnoExtra(models.Model):
    """L'ufficio cerca volontari (es. "domenica serve un 1° turno in più"): gli operai si
    offrono dall'app, l'ufficio sceglie e il turno compare nel calendario dei confermati."""

    data = models.DateField()
    fascia = models.CharField(
        max_length=10, choices=[(f.value, f.label) for f in Fascia if f in FASCE_LAVORATIVE and f != Fascia.ALTRO]
    )
    postazione = models.CharField(max_length=10, choices=Postazione.choices, blank=True)
    # chi può offrirsi: vuoto = chiunque
    ruolo = models.CharField(
        'chi serve', max_length=12, blank=True,
        choices=[c for c in Mansione.choices if c[0] != Mansione.UFFICIO],
    )
    posti = models.PositiveSmallIntegerField(default=1)
    nota = models.CharField(max_length=300, blank=True)
    chiusa = models.BooleanField(default=False)
    creata_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    creata_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'turno extra'
        verbose_name_plural = 'turni extra'
        ordering = ['data', 'creata_il']

    def __str__(self):
        return f'{self.data:%d/%m} {self.descrizione}'

    @property
    def descrizione(self):
        parti = [self.get_fascia_display()]
        if self.postazione:
            parti.append(self.get_postazione_display())
        return ' · '.join(parti)

    @property
    def sigla(self):
        return Turno.SIGLE.get(self.fascia, '?')

    @property
    def descrizione_fascia(self):
        return self.get_fascia_display()

    @property
    def nome_postazione(self):
        return self.get_postazione_display() if self.postazione else ''

    @property
    def orario(self):
        return ORARI.get(self.fascia, '')

    @property
    def classe_fascia(self):
        return Turno(fascia=self.fascia).classe_fascia

    @property
    def confermati(self):
        return [d for d in self.disponibilita.all() if d.confermata]

    @property
    def mancano(self):
        return max(0, self.posti - len(self.confermati))


class Disponibilita(models.Model):
    extra = models.ForeignKey(TurnoExtra, on_delete=models.CASCADE, related_name='disponibilita')
    dipendente = models.ForeignKey(Dipendente, on_delete=models.CASCADE, related_name='disponibilita')
    confermata = models.BooleanField(default=False)
    creata_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'disponibilità'
        ordering = ['creata_il']
        constraints = [models.UniqueConstraint(fields=['extra', 'dipendente'], name='una_disponibilita')]


class AvvisoAssenza(models.Model):
    """Malattia, uscita anticipata, ritardo: lo vedono solo il responsabile turni e il capo turno."""

    class Tipo(models.TextChoices):
        MALATTIA = 'MALATTIA', 'Malattia'
        USCITA = 'USCITA', 'Uscita anticipata'
        RITARDO = 'RITARDO', 'Ritardo'
        ALTRO = 'ALTRO', 'Altro'

    dipendente = models.ForeignKey(Dipendente, on_delete=models.CASCADE, related_name='avvisi')
    data = models.DateField()
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    nota = models.CharField(max_length=300, blank=True)
    creato_il = models.DateTimeField(auto_now_add=True)
    visto_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    visto_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'avviso di assenza'
        verbose_name_plural = 'avvisi di assenza'
        ordering = ['-creato_il']

    def __str__(self):
        return f'{self.dipendente} {self.data:%d/%m} {self.get_tipo_display()}'


# ---------------------------------------------------------------- Messaggi


class Annuncio(models.Model):
    """Bacheca: scrive solo il responsabile turni, leggono tutti."""

    testo = models.TextField(max_length=2000)
    importante = models.BooleanField(default=False)
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    creato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'annunci'
        ordering = ['-creato_il']


class Chat(models.Model):
    """Una chat di gruppo. "Tutti" = ogni utente attivo; altrimenti solo i membri scelti.
    La direzione è sempre dentro: le chat sono lo storico dell'azienda."""

    nome = models.CharField(max_length=60, unique=True)
    emoji = models.CharField(max_length=8, blank=True)
    tutti = models.BooleanField('aperta a tutti', default=True)
    membri = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='chat')
    ordine = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name_plural = 'chat'
        ordering = ['ordine', 'nome']

    def __str__(self):
        return self.nome


class MessaggioChat(models.Model):
    """Messaggio in una chat di gruppo."""

    chat = models.ForeignKey(Chat, null=True, on_delete=models.CASCADE, related_name='messaggi')
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    testo = models.TextField(max_length=1000)
    creato_il = models.DateTimeField(auto_now_add=True)
    eliminato = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'messaggio chat'
        verbose_name_plural = 'messaggi chat'
        ordering = ['creato_il']


class StatoMessaggi(models.Model):
    """Fin dove ha letto ogni utente (per i pallini dei non letti) e se vuole le notifiche della chat."""

    utente = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='stato_messaggi')
    bacheca_letta_il = models.DateTimeField(null=True, blank=True)
    chat_letta_fino = models.PositiveBigIntegerField(default=0)
    notifiche_chat = models.BooleanField(default=True)


class LetturaChat(models.Model):
    """Fin dove ha letto ogni utente in ciascuna chat (per i non letti)."""

    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='letture_chat')
    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name='letture')
    letta_fino = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['utente', 'chat'], name='una_lettura_per_chat')]


class IscrizionePush(models.Model):
    """Un telefono che ha accettato le notifiche."""

    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='iscrizioni_push')
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    creata_il = models.DateTimeField(auto_now_add=True)


class ChiaviPush(models.Model):
    """Chiavi VAPID generate dall'app al primo uso: niente segreti da copiare su Railway."""

    privata_pem = models.TextField()
    pubblica = models.CharField(max_length=200)


class BloccoAccesso(models.Model):
    """Tentativi di accesso sbagliati, per nome utente ("u:...") e per indirizzo di rete ("ip:...")."""

    chiave = models.CharField(max_length=200, unique=True)
    tentativi = models.PositiveIntegerField(default=0)
    bloccato_fino = models.DateTimeField(null=True, blank=True)
    aggiornato_il = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'blocco accesso'
        verbose_name_plural = 'blocchi accesso'


# ================================================================ manutenzione
# Registro di macchine e mezzi, ordini di lavoro (guasti e programmate), ricambi e ordini.


class Luogo(models.TextChoices):
    IMP1 = 'IMP1', 'Impianto 1'
    IMP2 = 'IMP2', 'Impianto 2'
    PIAZZALE = 'PIAZZALE', 'Piazzale'
    METALLI = 'METALLI', 'Metalli'
    SABBIA = 'SABBIA', 'Sabbia'
    MEZZI = 'MEZZI', 'Mezzi interni'
    ESTERNI = 'ESTERNI', 'Mezzi esterni'


class Macchina(models.Model):
    class Tipo(models.TextChoices):
        IMPIANTO = 'IMPIANTO', 'Macchinario / attrezzatura'
        MEZZO = 'MEZZO', 'Mezzo'

    codice = models.CharField(max_length=20, unique=True)
    nome = models.CharField(max_length=80)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.IMPIANTO)
    categoria = models.CharField(max_length=40, blank=True, help_text='Es. pala gommata, muletto, nastro, vaglio')
    luogo = models.CharField(max_length=10, choices=Luogo.choices)
    marca = models.CharField(max_length=40, blank=True)
    modello = models.CharField(max_length=60, blank=True)
    matricola = models.CharField('matricola / targa', max_length=40, blank=True)
    anno = models.PositiveSmallIntegerField(null=True, blank=True)
    contaore = models.PositiveIntegerField('ore motore', null=True, blank=True)
    note = models.TextField(blank=True)
    attiva = models.BooleanField(default=True)
    esempio = models.BooleanField(default=False, help_text="Macchina d'esempio, da togliere quando arriva l'elenco vero")

    class Meta:
        verbose_name_plural = 'macchine'
        ordering = ['luogo', 'tipo', 'nome']

    def __str__(self):
        return f'{self.nome} ({self.get_luogo_display()})'

    @property
    def icona(self):
        c = self.categoria.lower()
        for parola, emoji in (('pala', '🚜'), ('escavat', '🚜'), ('muletto', '🏗️'), ('camion', '🚛'),
                              ('nastro', '➰'), ('vaglio', '🔩'), ('tritur', '⚙️'), ('pressa', '🗜️'),
                              ('compress', '💨'), ('separat', '🧲'), ('pesa', '⚖️')):
            if parola in c:
                return emoji
        return '🚜' if self.tipo == self.Tipo.MEZZO else '⚙️'


class Intervento(models.Model):
    """Ordine di lavoro: un guasto segnalato o una manutenzione programmata."""

    class Tipo(models.TextChoices):
        GUASTO = 'GUASTO', 'Guasto'
        PROGRAMMATA = 'PROGRAMMATA', 'Programmata'
        LAVORO = 'LAVORO', 'Lavoro fatto'  # ripristino o sostituzione registrato senza segnalazione

    class Priorita(models.IntegerChoices):
        BASSA = 1, 'Bassa'
        NORMALE = 2, 'Normale'
        ALTA = 3, 'Alta'
        URGENTE = 4, 'Urgente'

    class Stato(models.TextChoices):
        SEGNALATA = 'SEGNALATA', 'Da approvare'
        ASSEGNATA = 'ASSEGNATA', 'Assegnata'
        IN_CORSO = 'IN_CORSO', 'In lavorazione'
        ATTESA_PEZZI = 'ATTESA_PEZZI', 'Attesa pezzi'
        COMPLETATA = 'COMPLETATA', 'Riparata'
        RIFIUTATA = 'RIFIUTATA', 'Rifiutata'

    APERTI = [Stato.SEGNALATA, Stato.ASSEGNATA, Stato.IN_CORSO, Stato.ATTESA_PEZZI]

    macchina = models.ForeignKey(Macchina, on_delete=models.PROTECT, related_name='interventi')
    tipo = models.CharField(max_length=12, choices=Tipo.choices, default=Tipo.GUASTO)
    descrizione = models.TextField('cosa succede')
    macchina_ferma = models.BooleanField(default=False)
    priorita = models.PositiveSmallIntegerField(choices=Priorita.choices, default=Priorita.NORMALE)
    stato = models.CharField(max_length=12, choices=Stato.choices, default=Stato.SEGNALATA)
    segnalata_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    segnalata_il = models.DateTimeField(default=timezone.now)
    foto_guasto = models.ImageField(upload_to='manutenzione/%Y/%m/', blank=True)
    approvata_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    approvata_il = models.DateTimeField(null=True, blank=True)
    assegnata_a = models.ForeignKey('Dipendente', null=True, blank=True, on_delete=models.SET_NULL, related_name='interventi')
    iniziata_il = models.DateTimeField(null=True, blank=True)
    completata_il = models.DateTimeField(null=True, blank=True)
    completata_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    lavoro_svolto = models.TextField(blank=True)
    foto_riparazione = models.ImageField(upload_to='manutenzione/%Y/%m/', blank=True)
    ore_lavoro = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    motivo_rifiuto = models.CharField(max_length=300, blank=True)
    piano = models.ForeignKey('ManutenzioneProgrammata', null=True, blank=True, on_delete=models.SET_NULL, related_name='interventi')

    class Meta:
        verbose_name_plural = 'interventi'
        ordering = ['-priorita', 'segnalata_il']

    def __str__(self):
        return f'#{self.pk} {self.macchina.nome}'

    @property
    def aperto(self):
        return self.stato in self.APERTI

    @property
    def classe_stato(self):
        return {
            'SEGNALATA': 'attesa', 'ASSEGNATA': 'blu', 'IN_CORSO': 'blu', 'ATTESA_PEZZI': 'viola',
            'COMPLETATA': 'ok', 'RIFIUTATA': 'spento',
        }[self.stato]

    @property
    def etichetta_stato(self):
        if self.tipo == self.Tipo.LAVORO:
            return 'Fatto'
        if self.stato == self.Stato.SEGNALATA and self.tipo == self.Tipo.PROGRAMMATA:
            return 'Da assegnare'
        return self.get_stato_display()

    @staticmethod
    def _nome(utente):
        if utente is None:
            return ''
        dip = getattr(utente, 'dipendente', None)
        return dip.nome_breve if dip else 'Ufficio'

    @property
    def chi_ha_segnalato(self):
        if self.segnalata_da_id:
            return self._nome(self.segnalata_da)
        return 'Programmata' if self.tipo == self.Tipo.PROGRAMMATA else ''

    @property
    def chi_ha_approvato(self):
        return self._nome(self.approvata_da)

    @property
    def chi_ha_sistemato(self):
        if self.completata_da_id:
            return self._nome(self.completata_da)
        return self.assegnata_a.nome_breve if self.assegnata_a_id and self.stato == self.Stato.COMPLETATA else ''

    @property
    def ore_fermo(self):
        """Ore di macchina ferma, dalla segnalazione alla riparazione (o a ora se ancora aperta)."""
        if not self.macchina_ferma:
            return 0
        fine = self.completata_il or timezone.now()
        return round((fine - self.segnalata_il).total_seconds() / 3600, 1)


class FotoIntervento(models.Model):
    """Foto in più di un intervento (es. prima, durante e dopo una sostituzione)."""

    intervento = models.ForeignKey(Intervento, on_delete=models.CASCADE, related_name='altre_foto')
    foto = models.ImageField(upload_to='manutenzione/%Y/%m/')
    caricata_il = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['pk']


class EventoIntervento(models.Model):
    """Diario dell'intervento: cambi di stato e note di chi ci lavora."""

    intervento = models.ForeignKey(Intervento, on_delete=models.CASCADE, related_name='eventi')
    autore = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    testo = models.CharField(max_length=500)
    nota = models.BooleanField(default=False)  # scritta a mano (non un cambio di stato)
    creato_il = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['creato_il', 'pk']


class Ricambio(models.Model):
    codice = models.CharField(max_length=40, blank=True)
    nome = models.CharField(max_length=100)
    fornitore = models.CharField(max_length=80, blank=True)
    scorta = models.IntegerField(default=0)
    scorta_minima = models.PositiveIntegerField(default=0)
    unita = models.CharField(max_length=8, default='pz')
    ubicazione = models.CharField('dove si trova', max_length=60, blank=True)
    costo = models.DecimalField('costo unitario €', max_digits=9, decimal_places=2, null=True, blank=True)
    macchine = models.ManyToManyField(Macchina, blank=True, related_name='ricambi')
    esempio = models.BooleanField(default=False)

    class Meta:
        verbose_name_plural = 'ricambi'
        ordering = ['nome']

    def __str__(self):
        return f'{self.nome}{f" ({self.codice})" if self.codice else ""}'

    @property
    def sotto_scorta(self):
        return self.scorta <= self.scorta_minima and self.scorta_minima > 0


class RicambioUsato(models.Model):
    intervento = models.ForeignKey(Intervento, on_delete=models.CASCADE, related_name='ricambi_usati')
    ricambio = models.ForeignKey(Ricambio, null=True, blank=True, on_delete=models.SET_NULL, related_name='usi')
    descrizione = models.CharField(max_length=100, blank=True)
    quantita = models.PositiveIntegerField(default=1)

    @property
    def nome(self):
        return self.ricambio.nome if self.ricambio else self.descrizione


class OrdineRicambio(models.Model):
    class Stato(models.TextChoices):
        RICHIESTO = 'RICHIESTO', 'Da approvare'
        APPROVATO = 'APPROVATO', 'Da ordinare'
        ORDINATO = 'ORDINATO', 'Ordinato'
        ARRIVATO = 'ARRIVATO', 'Arrivato'
        ANNULLATO = 'ANNULLATO', 'Annullato'

    intervento = models.ForeignKey(Intervento, null=True, blank=True, on_delete=models.SET_NULL, related_name='ordini')
    macchina = models.ForeignKey(Macchina, null=True, blank=True, on_delete=models.SET_NULL, related_name='ordini')
    ricambio = models.ForeignKey(Ricambio, null=True, blank=True, on_delete=models.SET_NULL, related_name='ordini')
    descrizione = models.CharField('pezzo', max_length=120, blank=True)
    quantita = models.PositiveIntegerField(default=1)
    urgente = models.BooleanField(default=False)
    nota = models.CharField(max_length=300, blank=True)
    foto = models.ImageField(upload_to='manutenzione/%Y/%m/', blank=True)
    stato = models.CharField(max_length=10, choices=Stato.choices, default=Stato.RICHIESTO)
    richiesto_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    richiesto_il = models.DateTimeField(default=timezone.now)
    approvato_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    fornitore = models.CharField(max_length=80, blank=True)
    ordinato_il = models.DateTimeField(null=True, blank=True)
    arrivato_il = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'ordine ricambio'
        verbose_name_plural = 'ordini ricambi'
        ordering = ['-urgente', '-richiesto_il']

    @property
    def nome(self):
        return self.ricambio.nome if self.ricambio else self.descrizione

    @property
    def classe_stato(self):
        return {'RICHIESTO': 'attesa', 'APPROVATO': 'attesa', 'ORDINATO': 'blu', 'ARRIVATO': 'ok', 'ANNULLATO': 'spento'}[self.stato]

    @property
    def aperto(self):
        return self.stato in (self.Stato.RICHIESTO, self.Stato.APPROVATO, self.Stato.ORDINATO)


class ManutenzioneProgrammata(models.Model):
    """Manutenzione periodica: alla scadenza diventa un intervento da assegnare."""

    macchina = models.ForeignKey(Macchina, on_delete=models.CASCADE, related_name='programmate')
    attivita = models.CharField('attività', max_length=120)
    istruzioni = models.TextField(blank=True, help_text='Una riga per ogni controllo da fare')
    ogni_giorni = models.PositiveSmallIntegerField('ogni quanti giorni')
    ultima = models.DateField('ultima volta', null=True, blank=True)
    attiva = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'manutenzione programmata'
        verbose_name_plural = 'manutenzioni programmate'
        ordering = ['macchina__luogo', 'macchina__nome']

    def __str__(self):
        return f'{self.attivita} · {self.macchina.nome}'

    @property
    def prossima(self):
        if self.ultima is None:
            return timezone.localdate()
        return self.ultima + timedelta(days=self.ogni_giorni)

    @property
    def righe_istruzioni(self):
        return [r.strip() for r in self.istruzioni.splitlines() if r.strip()]


class FermoImpianto(models.Model):
    """Interruzione di un intero impianto (es. rottura nastro, tramoggia bloccata) fino alla ripartenza."""

    IMPIANTI = [('IMP1', 'Impianto 1'), ('IMP2', 'Impianto 2'), ('SABBIA', 'Sabbia'), ('METALLI', 'Metalli')]

    class Causa(models.TextChoices):
        NASTRO = 'NASTRO', 'Rottura nastro'
        TRAMOGGIA = 'TRAMOGGIA', 'Blocco tramoggia'
        MACCHINA = 'MACCHINA', 'Guasto a una macchina'
        ALTRO = 'ALTRO', 'Altro guasto'

    impianto = models.CharField(max_length=10, choices=IMPIANTI)
    causa = models.CharField(max_length=10, choices=Causa.choices)
    macchina = models.ForeignKey(Macchina, null=True, blank=True, on_delete=models.SET_NULL, related_name='fermi')
    descrizione = models.CharField('cosa è successo', max_length=500, blank=True)
    foto = models.ImageField(upload_to='manutenzione/%Y/%m/', blank=True)
    fermo_dal = models.DateTimeField(default=timezone.now)
    segnalato_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+')
    intervento = models.ForeignKey(Intervento, null=True, blank=True, on_delete=models.SET_NULL, related_name='fermi')
    ripartito_il = models.DateTimeField(null=True, blank=True)
    ripartenza_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    sistemazione = models.CharField('cosa è stato sistemato', max_length=500, blank=True)
    foto_ripartenza = models.ImageField(upload_to='manutenzione/%Y/%m/', blank=True)

    class Meta:
        verbose_name = 'fermo impianto'
        verbose_name_plural = 'fermi impianto'
        ordering = ['-fermo_dal']

    def __str__(self):
        return f'{self.get_impianto_display()} fermo dal {timezone.localtime(self.fermo_dal):%d/%m %H:%M}'

    @property
    def in_corso(self):
        return self.ripartito_il is None

    @property
    def minuti(self):
        fine = self.ripartito_il or timezone.now()
        return max(0, int((fine - self.fermo_dal).total_seconds() // 60))

    @property
    def durata(self):
        m = self.minuti
        return f'{m // 60} h {m % 60:02d} min' if m >= 60 else f'{m} min'

    @property
    def chi_ha_segnalato(self):
        return Intervento._nome(self.segnalato_da)

    @property
    def chi_ha_fatto_ripartire(self):
        return Intervento._nome(self.ripartenza_da)
