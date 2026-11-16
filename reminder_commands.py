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


def parse_delete_request(text):
    """Return the requested reminder name, or '' if a name is missing."""
    text = re.sub(r'^\s*jarvis\s*[,!:;-]?\s*', '', text.strip(), flags=re.I)
    text = re.sub(r'\s*[,;]?\s*por favor[.!?]*\s*$', '', text, flags=re.I).strip(' .!¡?¿')
    match = re.fullmatch(r'(?:(?:quiero que|puedes|podr[ií]as|puedes por favor)\s+(?:me\s+)?)?(?:elimines|borres|quites|canceles|elimina|eliminar|borra|borrar|quita|quitar|cancela|cancelar)\s+(?:(?:el|un|mi|este|ese)\s+)?recordatorio(?:\s+(?:(?:de|sobre|para|que dice)\s+)?(.+))?', text, re.I)
    if not match:
        return None
    name = (match.group(1) or '').strip(' "\'.,!¡?¿')
    # Relative references, dates and bulk commands need an explicit clarification.
    if name.casefold() in ('todos', 'todo', 'ese', 'este', 'último', 'ultimo'):
        return ''
    return name


def find_matching_reminders(name, reminders):
    import unicodedata
    def normalize(value):
        value = unicodedata.normalize('NFKD', value.casefold())
        return ' '.join(''.join(c for c in value if not unicodedata.combining(c)).split())
    needle = normalize(name)
    if not needle:
        return []
    valid = [r for r in reminders if isinstance(r, dict) and type(r.get('id')) is int and isinstance(r.get('title'), str)]
    date = re.fullmatch(r'(.+?)\s+(?:del|de)\s+(\d{1,2})/(\d{1,2})/(\d{4})\s+a las\s+(\d{1,2}):(\d{2})', needle)
    if date:
        needle = date.group(1).strip()
        day, month, year, hour, minute = map(int, date.groups()[1:])
        filtered = []
        for reminder in valid:
            try:
                when = datetime.fromisoformat(reminder['when'])
                if (when.day, when.month, when.year, when.hour, when.minute) == (day, month, year, hour, minute):
                    filtered.append(reminder)
            except (KeyError, TypeError, ValueError):
                continue
        valid = filtered
    exact = [r for r in valid if normalize(r['title']) == needle]
    if exact:
        return exact
    return [r for r in valid if len(needle) >= 3 and needle in normalize(r['title'])]


def select_reminders_by_time(text, reminders):
    """Select by a spoken or typed hour; never guess AM/PM when both match."""
    text = text.strip().casefold().strip(' .!¡?¿,')
    text = re.sub(r'^(?:el|la|ese|esa)\s+(?:de\s+)?', '', text)
    text = re.sub(r'^(?:a\s+)?(?:las|la)\s+', '', text)
    text = re.sub(r'^a\s+', '', text)
    hour_words = {k: v for k, v in NUMBERS.items() if 1 <= v <= 12}
    hour_pattern = r'(?:\d{1,2}|' + '|'.join(hour_words) + ')'
    match = re.fullmatch(rf'({hour_pattern})(?::(\d{{2}})|\s+y\s+(\d{{1,2}}|media|cuarto))?(?:\s+(?:de\s+la\s+)?(mañana|manana|tarde|noche|madrugada)|\s*(a\.?m\.?|p\.?m\.?))?', text)
    if not match:
        return None
    hour_text, numeric_minute, spoken_minute, period, meridian = match.groups()
    hour = int(hour_text) if hour_text.isdecimal() else hour_words[hour_text]
    minute = int(numeric_minute) if numeric_minute else (30 if spoken_minute == 'media' else 15 if spoken_minute == 'cuarto' else int(spoken_minute) if spoken_minute else None)
    if hour > 23 or (minute is not None and minute > 59):
        return None
    if (period or meridian) and not 1 <= hour <= 12:
        return None
    matches = []
    for item in reminders:
        try:
            dt = datetime.fromisoformat(item['when'])
        except (KeyError, TypeError, ValueError):
            continue
        if 1 <= hour <= 12:
            if (dt.hour % 12 or 12) != hour:
                continue
        elif dt.hour != hour:
            continue
        if minute is not None and dt.minute != minute:
            continue
        if meridian and ((meridian.startswith('a') and dt.hour >= 12) or (meridian.startswith('p') and dt.hour < 12)):
            continue
        if period in ('mañana', 'manana') and not 6 <= dt.hour < 12:
            continue
        if period == 'madrugada' and not 0 <= dt.hour < 6:
            continue
        if period == 'tarde' and not 12 <= dt.hour < 19:
            continue
        if period == 'noche' and not 19 <= dt.hour <= 23:
            continue
        matches.append(item)
    return matches


def select_reminders_by_date(text, reminders, now=None):
    text = text.strip().casefold().strip(' .!¡?¿,')
    text = re.sub(r'^(?:el|la|ese|esa)\s+(?:de\s+)?', '', text)
    current = (now or datetime.now().astimezone()).date()
    from datetime import timedelta
    if text in ('hoy', 'mañana', 'manana', 'ayer'):
        delta = 1 if text in ('mañana', 'manana') else -1 if text == 'ayer' else 0
        target = current + timedelta(days=delta)
    else:
        match = re.fullmatch(r'(?:del?\s+)?(\d{1,2})/(\d{1,2})(?:/(\d{4}))?', text)
        if not match:
            return None
        try:
            target = current.replace(year=int(match.group(3)) if match.group(3) else current.year,
                                     month=int(match.group(2)), day=int(match.group(1)))
        except ValueError:
            return None
    results = []
    for item in reminders:
        try:
            if datetime.fromisoformat(item['when']).date() == target:
                results.append(item)
        except (KeyError, ValueError, TypeError):
            pass
    return results


def select_reminders_by_period(text, reminders):
    text = re.sub(r'^(?:el|la)?\s*(?:de\s+la\s+)?', '', text.strip().casefold().strip(' .!¡?¿,'))
    ranges = {'mañana': (6, 12), 'manana': (6, 12), 'madrugada': (0, 6),
              'tarde': (12, 19), 'noche': (19, 24), 'am': (0, 12), 'pm': (12, 24)}
    text = text.replace('.', '').strip()
    if text not in ranges:
        return None
    start, end = ranges[text]
    return [item for item in reminders if start <= datetime.fromisoformat(item['when']).hour < end]


def select_reminders_by_minute(text, reminders):
    text = re.sub(r'^(?:y\s+|con\s+)', '', text.strip().casefold().strip(' .!¡?¿,'))
    if text in ('media', 'treinta'):
        minute = 30
    elif text == 'cuarto':
        minute = 15
    elif text in ('en punto', 'cero'):
        minute = 0
    elif text.isdecimal() and 0 <= int(text) <= 59:
        minute = int(text)
    else:
        return None
    return [item for item in reminders if datetime.fromisoformat(item['when']).minute == minute]
