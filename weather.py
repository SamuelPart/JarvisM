"""On-demand Open-Meteo weather, OSM geocoding and bundled country capitals."""
from __future__ import annotations
import math
import json
from pathlib import Path
import re
import unicodedata
import requests

USER_AGENT = 'JarvisM/1.0 (desktop weather; https://github.com/SamuelPart/JarvisM)'
CONDITIONS = {
    0: ('Despejado', 'sun'), 1: ('Mayormente despejado', 'sun'), 2: ('Parcialmente nublado', 'partly'),
    3: ('Nublado', 'cloud'), 45: ('Niebla', 'cloud'), 48: ('Niebla con escarcha', 'cloud'),
    51: ('Llovizna ligera', 'rain'), 53: ('Llovizna', 'rain'), 55: ('Llovizna intensa', 'rain'),
    56: ('Llovizna helada ligera', 'rain'), 57: ('Llovizna helada intensa', 'rain'),
    61: ('Lluvia ligera', 'rain'), 63: ('Lluvia moderada', 'rain'), 65: ('Lluvia intensa', 'rain'),
    66: ('Lluvia helada ligera', 'rain'), 67: ('Lluvia helada intensa', 'rain'),
    71: ('Nieve ligera', 'snow'), 73: ('Nieve moderada', 'snow'), 75: ('Nieve intensa', 'snow'),
    77: ('Granos de nieve', 'snow'), 80: ('Chubascos ligeros', 'rain'), 81: ('Chubascos moderados', 'rain'),
    82: ('Chubascos intensos', 'rain'), 85: ('Chubascos de nieve', 'snow'), 86: ('Nieve intensa', 'snow'),
    95: ('Tormenta', 'storm'), 96: ('Tormenta con granizo', 'storm'), 99: ('Tormenta con granizo intenso', 'storm'),
}


class WeatherError(Exception):
    pass


def _norm(value):
    value = unicodedata.normalize('NFKD', str(value).casefold())
    return ' '.join(''.join(c for c in value if not unicodedata.combining(c)).split())


def _fetch(url, params):
    service = 'OpenStreetMap' if 'nominatim.openstreetmap.org' in url else 'Open-Meteo'
    try:
        response = requests.get(url, params=params, headers={'User-Agent': USER_AGENT, 'Accept-Language': 'es'},
                                timeout=(5, 12), allow_redirects=False)
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise WeatherError(f'{service} no respondió correctamente (HTTP {response.status_code}). Inténtalo de nuevo.')
        return response.json()
    except requests.Timeout as exc:
        raise WeatherError(f'{service} tardó demasiado en responder. Inténtalo de nuevo.') from exc
    except requests.RequestException as exc:
        raise WeatherError(f'No pude conectar con {service}. Revisa la conexión o inténtalo más tarde.') from exc
    except ValueError as exc:
        raise WeatherError(f'{service} devolvió una respuesta inválida.') from exc


def _country(name):
    # Country names and capitals are bundled locally, so a third-party country
    # lookup outage cannot prevent a weather request. Only exact aliases match.
    try:
        with (Path(__file__).resolve().parent / 'data' / 'countries.json').open(encoding='utf-8') as source:
            countries = json.load(source)
    except (OSError, ValueError) as exc:
        raise WeatherError('No pude leer la lista local de países. Actualiza o reinstala JARVIS.') from exc
    wanted = _norm(name)
    matches = []
    for item in countries:
        base = item.get('name') or {}
        translations = item.get('translations') or {}
        names = [base.get('common', ''), base.get('official', ''), item.get('cca2', ''), item.get('cca3', '')]
        names.extend(item.get('altSpellings') or [])
        for entry in translations.values():
            if isinstance(entry, dict):
                names.extend([entry.get('common', ''), entry.get('official', '')])
        if wanted and wanted in {_norm(n) for n in names if isinstance(n, str) and n}:
            matches.append(item)
    return matches[0] if len(matches) == 1 else None


def _geocode(query, forced_country=None, allow_top=False):
    values = _fetch('https://nominatim.openstreetmap.org/search',
                    {'q': query, 'format': 'jsonv2', 'addressdetails': 1, 'limit': 5})
    if not isinstance(values, list):
        raise WeatherError('No encontré esa ubicación. Dime una ciudad o región y su país.')
    candidates = []
    seen = set()
    for item in values:
        if not isinstance(item, dict):
            continue
        addr = item.get('address') if isinstance(item.get('address'), dict) else {}
        if forced_country and str(addr.get('country_code', '')).upper() != forced_country.upper():
            continue
        try:
            lat, lon = float(item['lat']), float(item['lon'])
        except (KeyError, ValueError, TypeError):
            continue
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            continue
        if item.get('addresstype') in ('country', 'continent'):
            continue
        name = str(item.get('display_name') or '').strip()
        if not name:
            continue
        identity = (round(lat, 3), round(lon, 3))
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append({'latitude': lat, 'longitude': lon, 'label': name[:200],
                           'country': str(addr.get('country') or '')[:100],
                           'region': str(addr.get('state') or addr.get('region') or '')[:100],
                           'place': str(addr.get('city') or addr.get('town') or addr.get('village') or addr.get('municipality') or addr.get('state') or item.get('name') or query)[:100],
                           'country_code': str(addr.get('country_code') or '').upper(),
                           'importance': float(item.get('importance') or 0) if isinstance(item.get('importance'), (float, int)) else 0})
    if not candidates:
        raise WeatherError('No encontré esa ubicación. Dime una ciudad o región y su país.')
    if len(candidates) > 1 and not allow_top:
        first, second = candidates[:2]
        # An unqualified, highly prominent city is normally the intended location.
        # Otherwise ask instead of silently selecting an arbitrary homonym.
        if first['importance'] < 0.5 or first['importance'] < 2.5 * max(second['importance'], .01):
            return {'ambiguous': True, 'options': [c['label'] for c in candidates[:3]]}
    return candidates[0]


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def get_weather(location):
    if not isinstance(location, str) or not location.strip() or len(location) > 150:
        raise WeatherError('Indica una ciudad, región o país para consultar el clima.')
    location = re.sub(r'\s+', ' ', location).strip(' ,')
    country, is_capital = None, False
    country_error = None
    if ',' not in location:
        try:
            country = _country(location)
        except WeatherError as exc:
            # A geocoder may still resolve a city if the local list is unavailable.
            country_error = exc
    if country:
        capitals = country.get('capital') or []
        code = country.get('cca2') or ''
        if not isinstance(capitals, list) or len(capitals) != 1 or not isinstance(capitals[0], str):
            raise WeatherError('Ese país tiene varias capitales o no tiene una capital definida. Dime una ciudad o región.')
        city = capitals[0]
        location_data = _geocode(city + ', ' + location, forced_country=code, allow_top=True)
        is_capital = True
    else:
        query = location
        explicit_country = None
        # Users naturally say "La Libertad de Perú". Preserve the region and
        # only rewrite the final qualifier when it is an actual country.
        match = re.fullmatch(r'(.+?)\s+de\s+([^,]+)', location, flags=re.I)
        if match:
            try:
                qualifier = _country(match.group(2))
            except WeatherError:
                qualifier = None
            if qualifier:
                query = match.group(1) + ', ' + match.group(2)
                explicit_country = qualifier.get('cca2') or None
        try:
            location_data = _geocode(query, forced_country=explicit_country)
        except WeatherError as exc:
            if country_error and str(exc).startswith('No encontré esa ubicación'):
                raise country_error from exc
            raise
    if location_data.get('ambiguous'):
        return {'ambiguous': True, 'location': location, 'options': location_data['options']}
    values = _fetch('https://api.open-meteo.com/v1/forecast', {
        'latitude': location_data['latitude'], 'longitude': location_data['longitude'],
        'current': 'temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m',
        'daily': 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max,sunrise,sunset',
        'timezone': 'auto', 'forecast_days': 3,
    })
    if not isinstance(values, dict) or not isinstance(values.get('current'), dict):
        raise WeatherError('El servicio no devolvió datos del clima para esa ubicación.')
    current = values['current']
    temperature = _number(current.get('temperature_2m'))
    code = current.get('weather_code')
    observed_at = current.get('time')
    if temperature is None or type(code) is not int or not isinstance(observed_at, str):
        raise WeatherError('El servicio devolvió datos incompletos del clima.')
    description, icon = CONDITIONS.get(code, ('Condiciones no disponibles', 'cloud'))
    daily_data = values.get('daily') if isinstance(values.get('daily'), dict) else {}
    dates = daily_data.get('time') if isinstance(daily_data.get('time'), list) else []
    daily = []
    def daily_value(key, index):
        arr = daily_data.get(key)
        return arr[index] if isinstance(arr, list) and index < len(arr) else None
    for index, day in enumerate(dates[:3]):
        if not isinstance(day, str):
            continue
        day_code = daily_value('weather_code', index)
        day_desc, day_icon = CONDITIONS.get(day_code, ('Condiciones no disponibles', 'cloud'))
        daily.append({'date': day, 'description': day_desc, 'icon': day_icon,
                      'max': _number(daily_value('temperature_2m_max', index)),
                      'min': _number(daily_value('temperature_2m_min', index)),
                      'precipitation_probability': _number(daily_value('precipitation_probability_max', index)),
                      'uv': _number(daily_value('uv_index_max', index)),
                      'sunrise': daily_value('sunrise', index), 'sunset': daily_value('sunset', index)})
    return {'ok': True, 'location': location_data, 'is_capital': is_capital, 'requested': location,
            'current': {'temperature': temperature, 'feels_like': _number(current.get('apparent_temperature')),
                        'humidity': _number(current.get('relative_humidity_2m')), 'precipitation': _number(current.get('precipitation')),
                        'wind': _number(current.get('wind_speed_10m')), 'description': description, 'icon': icon,
                        'is_day': current.get('is_day') == 1, 'time': observed_at},
            'daily': daily, 'timezone': str(values.get('timezone') or ''),
            'source': 'Open-Meteo', 'geocoding': 'OpenStreetMap Nominatim',
            'note': 'Datos meteorológicos modelados más recientes del proveedor; pueden no ser mediciones en vivo.'}
