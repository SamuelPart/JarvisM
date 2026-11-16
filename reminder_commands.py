"""Resolve explicit relative reminders using the local clock, without a model."""
import re
from datetime import datetime

NUMBERS = {'un': 1, 'uno': 1, 'una': 1, 'dos': 2, 'tres': 3, 'cuatro': 4,
           'cinco': 5, 'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9,
           'diez': 10, 'once': 11, 'doce': 12, 'quince': 15, 'veinte': 20,
           'treinta': 30, 'cuarenta': 40, 'cincuenta': 50, 'sesenta': 60}
NUM = r'(?:[0-9]{1,4}|' + '|'.join(NUMBERS) + ')'
SPAN = rf'(?:dentro de|en)\s+({NUM})\s+(segundos?|minutos?|horas?)'


def parse_relative_reminder(text, now=None):
    text = re.sub(r'^\s*jarvis\s*[,!:;-]?\s*', '', text.strip(), flags=re.I)
    text = re.sub(r'\s*[,;]?\s*por favor[.!?]*\s*$', '', text, flags=re.I).strip(' .!¡?¿')
    match = re.fullmatch(rf'recu[eé]rdame\s+(.+?)\s+{SPAN}', text, flags=re.I)
    if match:
        title, amount, unit = match.groups()
    else:
        match = re.fullmatch(rf'{SPAN}\s*[,;]?\s*recu[eé]rdame\s+(.+)', text, flags=re.I)
        if not match:
            return None
        amount, unit, title = match.groups()
    amount = int(amount) if amount.isdecimal() else NUMBERS[amount.lower()]
    multiplier = 1 if unit.lower().startswith('segundo') else 60 if unit.lower().startswith('minuto') else 3600
    seconds = amount * multiplier
    if not 1 <= seconds <= 30 * 24 * 3600 or not title.strip() or len(title) > 300:
        return None
    now = now or datetime.now().astimezone()
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Se requiere hora local con zona.')
    when = datetime.fromtimestamp(now.timestamp() + seconds).astimezone()
    return {'title': title.strip(), 'when': when.isoformat(timespec='seconds')}
