"""Small explicit morning routine with a fixed application allowlist."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import startup_briefing

STATE = Path(__file__).resolve().parent / '.jarvis-routine.json'
APPLICATIONS = {
    'chrome': ('google-chrome-stable', 'google-chrome'),
    'firefox': ('firefox',),
    'whatsapp': ('whatsapp-for-linux', 'whatsapp'),
    'archivos': ('xdg-open',),
}
ALIASES = {'google chrome': 'chrome', 'chrome': 'chrome', 'firefox': 'firefox',
           'whatsapp': 'whatsapp', 'archivos': 'archivos'}


def open_app(name):
    if not isinstance(name, str):
        raise ValueError('Indica el nombre de una aplicación compatible.')
    key = ALIASES.get(name.strip().casefold())
    if key is None:
        return {'requested': False, 'error': 'Aplicación no compatible. Se admiten Chrome, Firefox, WhatsApp y Archivos.'}
    executable = next((p for binary in APPLICATIONS[key] if (p := shutil.which(binary))), None)
    if not executable:
        return {'requested': False, 'error': f'No encontré {name} instalado.'}
    args = [executable] + ([str(Path.home())] if key == 'archivos' else [])
    try:
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return {'requested': False, 'error': f'No pude iniciar {name}.'}
    return {'requested': True, 'application': key,
            'note': 'Se solicitó abrir la aplicación; no se verificó su ventana.'}


def configure(apps):
    if not isinstance(apps, str) or len(apps) > 200:
        raise ValueError('Indica aplicaciones separadas por comas, o ninguna.')
    names = [s.strip().casefold() for s in apps.split(',') if s.strip()]
    if names == ['ninguna']:
        names = []
    if any(name not in ALIASES for name in names):
        raise ValueError('Solo se admiten Chrome, Firefox, WhatsApp y Archivos.')
    names = list(dict.fromkeys(ALIASES[name] for name in names))
    filename = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=STATE.parent, delete=False) as f:
            filename = f.name
            json.dump({'apps': names}, f, ensure_ascii=False)
        os.replace(filename, STATE)
    finally:
        if filename and os.path.exists(filename):
            os.unlink(filename)
    return {'configured': names}


def run():
    try:
        data = json.loads(STATE.read_text(encoding='utf-8'))
        apps = data.get('apps', []) if isinstance(data, dict) else []
        if not isinstance(apps, list) or len(apps) > len(APPLICATIONS):
            apps = []
    except (OSError, ValueError):
        apps = []
    opened = [open_app(name) for name in apps if isinstance(name, str) and name in APPLICATIONS]
    try:
        summary = startup_briefing.build()
    except Exception:
        summary = 'No se pudo completar el resumen.'
    return {'summary': summary, 'applications': opened,
            'note': 'Las aplicaciones son solicitudes de apertura, no aperturas verificadas.'}
