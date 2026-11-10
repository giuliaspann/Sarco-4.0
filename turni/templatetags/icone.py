"""{% icona 'nome' %}: le icone a linea dell'app al posto delle emoji (stile Instagram).

Le icone sono quelle del Menu (views_menu.ICONE) più qualche voce in più usata nelle altre pagine.
"""
from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

EXTRA = {
    'mezzi': '<path d="M3 16V8h11v8M14 11h4l3 3v2h-7"/><circle cx="7" cy="17" r="2"/><circle cx="17" cy="17" r="2"/>',
    'segnaletica': '<path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17v.1"/>',
    'video': '<rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3"/>',
    'stampa': '<path d="M7 9V3h10v6M7 17H4v-7h16v7h-3"/><rect x="7" y="14" width="10" height="7"/>',
    'modifica': '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13 7l4 4"/>',
    'elimina': '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
    'posizione': '<path d="M12 21s7-6.5 7-12a7 7 0 0 0-14 0c0 5.5 7 12 7 12z"/><circle cx="12" cy="9" r="2.5"/>',
    'documento': '<path d="M6 3h9l4 4v14H6zM14 3v5h5"/>',
    'invia': '<path d="M3 20.5l18-8.5L3 3.5l2.5 8.5L3 20.5zM5.5 12H13"/>',
    'cerca': '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4 4"/>',
    'qr': '<path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h2v2h-2zM18 18h2v2h-2zM18 14h2M14 18v2"/>',
    'ok': '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.5 2.5L16 9.5"/>',
    'attenzione': '<path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17v.1"/>',
    'impianto': '<path d="M3 21V10l6 4V10l6 4V5h4v16z"/><path d="M7 17h2M12 17h2"/>',
    'sabbia': '<path d="M7 3h10M7 21h10M8 3c0 5 8 5 8 9s-8 4-8 9M16 3c0 5-8 5-8 9"/>',
    'nastro': '<circle cx="6" cy="14" r="3"/><circle cx="18" cy="14" r="3"/><path d="M6 11h12M6 17h12"/>',
    'corrente': '<path d="M13 3L5 14h6l-1 7 8-11h-6z"/>',
    'carburante': '<path d="M5 21V5a2 2 0 0 1 2-2h6a2 2 0 0 1 2 2v16M4 21h12M7 8h6M15 10h2a2 2 0 0 1 2 2v5a1.5 1.5 0 0 0 3 0V9l-3-3"/>',
    'altro': '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 1-1 1.7M12 17v.1"/>',
}

# emoji che arrivano dai dati (tipo di macchina, luogo, causa del fermo...) -> icona a linea
DA_EMOJI = {
    '🏭': 'impianto', '🔩': 'ricambi', '⚙': 'ricambi', '⏳': 'sabbia', '🅿': 'piazzale',
    '🚜': 'mezzi', '🚛': 'mezzi', '🚚': 'mezzi', '🏗': 'mezzi', '🧪': 'analisi', '🔬': 'analisi',
    '🔍': 'cerca', '🔎': 'cerca', '🧹': 'pulizia', '🪞': 'segnaletica', '🪧': 'segnaletica',
    '⛽': 'carburante', '➰': 'nastro', '🗜': 'macchine', '💨': 'macchine', '🧲': 'macchine', '🧱': 'macchine',
    '⚖': 'produzione', '📋': 'richieste', '🚫': 'fermo', '🛑': 'fermo', '⛔': 'fermo', '⚡': 'corrente',
    '❓': 'altro', '🔧': 'manutenzione', '🛠': 'manutenzione',
}


def _icone():
    from ..views_menu import ICONE
    return {**ICONE, **EXTRA}


@register.simple_tag
def icona(nome, classe='ico'):
    """SVG a linea: colore e spessore dal CSS (currentColor). Nome sconosciuto = nessuna icona."""
    disegno = _icone().get(nome)
    if not disegno:
        return ''
    return format_html('<svg class="{}" viewBox="0 0 24 24" aria-hidden="true">{}</svg>', classe, mark_safe(disegno))


@register.filter
def come_icona(emoji):
    """{{ macchina.icona|come_icona }}: l'emoji salvata nei dati diventa l'icona a linea corrispondente.
    Un'emoji che non conosce resta com'è, così non sparisce niente."""
    testo = str(emoji or '').replace('️', '').strip()
    nome = DA_EMOJI.get(testo)
    return icona(nome) if nome else emoji
