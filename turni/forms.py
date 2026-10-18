from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .sicurezza import MESSAGGIO_BLOCCO, ProtezioneAccesso

# Il file turni settimanale pesa qualche centinaio di KB: 5 MB bastano e avanzano
MAX_EXCEL = 5 * 1024 * 1024


class AccessoForm(ProtezioneAccesso, AuthenticationForm):
    """Login con nome utente e PIN, con blocco temporaneo dopo troppi PIN sbagliati."""

    username = forms.CharField(
        label='Nome utente',
        widget=forms.TextInput(attrs={'autocapitalize': 'none', 'autocomplete': 'username'}),
    )
    password = forms.CharField(
        label='PIN o password',
        strip=False,
        # niente tastiera solo numerica: l'ufficio entra con una password che può contenere lettere
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}),
    )

    error_messages = {
        **AuthenticationForm.error_messages,
        'invalid_login': 'Nome utente o PIN sbagliati.',
        'bloccato': MESSAGGIO_BLOCCO,
    }


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
        if f.size > MAX_EXCEL:
            raise forms.ValidationError('Il file è troppo grande (massimo 5 MB).')
        return f
