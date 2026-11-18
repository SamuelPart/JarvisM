"""Local NVIDIA credentials for the desktop app (Ajustes → Proveedor de IA).

Stores ONLY the API key in a local, gitignored JSON file with owner-only
permissions when the platform allows it. The key is never printed, never
logged and is only sent to NVIDIA NIM as an Authorization header. The
console entry point can alternatively use NVIDIA_API_KEY from .env.
"""
import json
import os
import re
import tempfile
from pathlib import Path

PATH = Path(__file__).resolve().parent / '.jarvis-provider.json'
KEY = 'nvidia_api_key'
_PATTERN = re.compile(r'^[A-Za-z0-9_-]{8,512}$')


def _path(path):
    return Path(path) if path else PATH


def is_valid_format(key):
    return bool(_PATTERN.fullmatch(key or ''))


def load_key(path=None):
    try:
        data = json.loads(_path(path).read_text(encoding='utf-8'))
        key = data.get(KEY) if isinstance(data, dict) else ''
        return key.strip() if isinstance(key, str) else ''
    except (OSError, ValueError, UnicodeError):
        return ''


def save_key(key, path=None):
    key = (key or '').strip()
    if not is_valid_format(key):
        raise ValueError('Formato de clave no válido.')
    path = _path(path)
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as file:
            name = file.name
            json.dump({KEY: key}, file)
        try:
            os.chmod(name, 0o600)
        except OSError:
            pass  # best effort on platforms without POSIX permissions
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    return True


def clear_key(path=None):
    try:
        _path(path).unlink()
    except FileNotFoundError:
        pass


def resolve_api_key(static='', path=None):
    """Single source of truth: settings file wins; .env/environment as fallback."""
    static = (static or '').strip()
    if static:
        return static
    key = load_key(path)
    if key:
        return key
    return os.environ.get('NVIDIA_API_KEY', '').strip()
