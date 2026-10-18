from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone


class Fascia(models.TextChoices):
    MATTINA = '1T', '1° turno'
    POMERIGGIO = '2T', '2° turno'
    NOTTE = 'N', 'Notte'
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


class Dipendente(models.Model):
    nome = models.CharField('nome come nel file turni', max_length=100, unique=True)
    utente = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='dipendente'
    )
    attivo = models.BooleanField(default=True)
    tutor = models.CharField('tutor (apprendisti)', max_length=200, blank=True)
    # Il PIN è corto: dopo troppi tentativi sbagliati l'accesso si blocca per un po'
    tentativi_falliti = models.PositiveSmallIntegerField(default=0, editable=False)
    bloccato_fino = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name_plural = 'dipendenti'
        ordering = ['nome']

    def __str__(self):
        return self.nome

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
        return ' · '.join(parti) or self.codice

    @property
    def nome_postazione(self):
        return self.get_postazione_display() if self.lavora and self.postazione else ''

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
        """Sigla corta per la casella del calendario."""
        return self.SIGLE.get(self.fascia, '?')

    SIGLE_POSTAZIONE = {
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


class MessaggioChat(models.Model):
    """Chat di gruppo: operai e ufficio."""

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
