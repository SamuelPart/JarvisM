"""Recognize common Spanish weather requests without invoking the model."""
import re


def parse_weather_request(text):
    clean = re.sub(r'^\s*jarvis\s*[,!:;-]?\s*', '', text.strip(), flags=re.I)
    clean = re.sub(r'\s*[,;]?\s*por favor[.!?]*\s*$', '', clean, flags=re.I).strip(' .!¡?¿')
    if re.search(r'\b(?:correos?|e-?mail|mensaje|recordatorio|env[ií]a|env[ií]es|enviar|manda|mandar)\b', clean, re.I):
        return None
    match = re.search(r'\b(?:clima|temperatura|pron[oó]stico(?:\s+del\s+tiempo)?|tiempo)\b', clean, re.I)
    if not match:
        return None
    if match.group(0).lower() == 'tiempo' and not re.search(r'\b(?:c[oó]mo|cu[aá]l|dime|ver|mu[eé]strame|consulta|qu[eé] tal|hace|est[aá])\b', clean, re.I):
        return None
    tail = clean[match.end():].strip()
    # Keep place qualifiers such as "La Libertad de Perú" together.
    found = list(re.finditer(r'\b(?:en|de|para)\s+', tail, flags=re.I))
    if not found:
        return ''
    first = found[0]
    remaining = tail[first.end():]
    if len(found) > 1 and re.match(r'(?:hoy|ahora|actualmente)\b', remaining, re.I):
        first = found[1]
    location = tail[first.end():].strip(' .!¡?¿,')
    location = re.sub(r'\s+(?:hoy|ahora|actual|actualmente|en este momento)$', '', location, flags=re.I).strip(' ,')
    if not location or location.casefold() in ('hoy', 'mañana', 'ahora', 'estos días'):
        return ''
    return location[:150]


def format_weather(result):
    if not isinstance(result, dict):
        return 'No pude obtener el clima; el servicio respondió de forma inesperada.'
    if result.get('ambiguous'):
        return 'Encontré varios lugares con ese nombre. ¿En qué país o región?'
    if result.get('error'):
        return str(result['error'])
    if result.get('ok') is not True:
        return 'No pude obtener el clima; el servicio respondió de forma inesperada.'
    current = result['current']
    location = result['location']
    place = location.get('place') or location.get('label') or result.get('requested', 'la ubicación')
    prefix = 'En ' + str(place)
    if result.get('is_capital'):
        prefix += ', capital de ' + str(result.get('requested'))
    return f"{prefix}, hay {current['temperature']:.0f} grados y {current['description'].lower()}, señor."
