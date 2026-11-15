"""Register the native host for Google Chrome on Linux; no browser credentials."""
import json
import os
import platform
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def install():
    if platform.system() != 'Linux':
        raise RuntimeError('La instalación automática solo está disponible para Google Chrome en Linux.')
    extension_id = (ROOT / 'chrome_extension' / 'extension_id.txt').read_text(encoding='utf-8').strip()
    host = ROOT / 'chrome_music_native.py'
    if not host.is_file() or not os.access(host, os.X_OK):
        raise RuntimeError('No se encuentra el programa de conexión ejecutable de JARVIS.')
    target = Path.home() / '.config/google-chrome/NativeMessagingHosts'
    target.mkdir(parents=True, exist_ok=True)
    manifest = {'name': 'com.jarvis.music', 'description': 'JARVIS: control limitado de YouTube',
                'path': str(host), 'type': 'stdio', 'allowed_origins': ['chrome-extension://' + extension_id + '/']}
    name = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=target, delete=False) as file:
            name = file.name
            json.dump(manifest, file, ensure_ascii=False, indent=2)
        os.replace(name, target / 'com.jarvis.music.json')
    finally:
        if name and os.path.exists(name):
            os.unlink(name)
    print('Conexión registrada. Carga la carpeta chrome_extension en chrome://extensions.')
    print('ID de la extensión:', extension_id)


if __name__ == '__main__':
    try:
        install()
    except (OSError, RuntimeError, ValueError) as exc:
        print('No se pudo registrar la extensión:', str(exc))
        raise SystemExit(1)
