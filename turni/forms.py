from datetime import timedelta

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.utils import timezone

from .models import Dipendente

TENTATIVI_MAX = 5
BLOCCO = timedelta(minutes=15)


class AccessoForm(AuthenticationForm):
    """Login con nome utente e PIN, con blocco temporaneo dopo troppi PIN sbagliati."""

    username = forms.CharField(
        label='Nome utente',
        widget=forms.TextInput(attrs={'autocapitalize': 'none', 'autocomplete': 'username', 'autofocus': True}),
    )
    password = forms.CharField(
        label='PIN',
        strip=False,
        widget=forms.PasswordInput(attrs={'inputmode': 'numeric', 'autocomplete': 'current-password'}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Nome utente o PIN sbagliati.',
        'bloccato': 'Troppi tentativi sbagliati: riprova tra qualche minuto o chiedi in ufficio.',
    }

    def clean(self):
        username = (self.cleaned_data.get('username') or '').strip().lower()
        self.cleaned_data['username'] = username
        dip = Dipendente.objects.filter(utente__username=username).first()
        if dip and dip.bloccato_fino and dip.bloccato_fino > timezone.now():
            raise forms.ValidationError(self.error_messages['bloccato'], code='bloccato')
        try:
            pulito = super().clean()
        except forms.ValidationError:
            if dip:
                dip.tentativi_falliti += 1
                if dip.tentativi_falliti >= TENTATIVI_MAX:
                    dip.bloccato_fino = timezone.now() + BLOCCO
                    dip.tentativi_falliti = 0
                dip.save(update_fields=['tentativi_falliti', 'bloccato_fino'])
            raise
        if dip and (dip.tentativi_falliti or dip.bloccato_fino):
            dip.tentativi_falliti = 0
            dip.bloccato_fino = None
            dip.save(update_fields=['tentativi_falliti', 'bloccato_fino'])
        return pulito


class ImportaForm(forms.Form):
    file = forms.FileField(label='File turni (.xlsx)')
    lunedi = forms.DateField(
        label='Lunedì della settimana',
        required=False,
        help_text='Lascia vuoto: lo prendo dal nome del file ("DAL 12-10-2026 AL ...").',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )

    def clean_file(self):
        f = self.cleaned_data['file']
        if not f.name.lower().endswith(('.xlsx', '.xlsm')):
            raise forms.ValidationError('Serve un file Excel .xlsx')
        return f
