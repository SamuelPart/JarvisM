"""Local, validated visual preferences, independent of the GUI toolkit."""
import json
import os
import tempfile
from pathlib import Path

DEFAULTS = {'color': 'azul', 'size': 'mediano', 'animation': 'normal', 'weather_sound': 'activado'}
OPTIONS = {'color': ('azul', 'cian', 'violeta', 'verde'),
           'size': ('pequeño', 'mediano', 'grande'),
           'animation': ('reducida', 'normal'),
           'weather_sound': ('activado', 'desactivado')}
PALETTES = {
    'azul': ((70, 81, 255), (128, 136, 255)),
    'cian': ((27, 180, 220), (115, 240, 255)),
    'violeta': ((143, 75, 255), (207, 153, 255)),
    'verde': ((29, 187, 139), (129, 247, 191)),
}
SCALES = {'pequeño': 0.8, 'mediano': 1.0, 'grande': 1.2}


def normalize(values):
    if not isinstance(values, dict):
        return DEFAULTS.copy()
    result = {}
    for key, default in DEFAULTS.items():
        value = values.get(key)
        if key == 'animation' and value == 'desactivada':
            value = 'reducida'
        result[key] = value if isinstance(value, str) and value in OPTIONS[key] else default
    return result


def load(path):
    try:
        return normalize(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError, ValueError, UnicodeError):
        return DEFAULTS.copy()


def save(path, values):
    path = Path(path)
    normalized = normalize(values)
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as file:
            name = file.name
            json.dump(normalized, file, ensure_ascii=False, indent=2)
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    return normalized
