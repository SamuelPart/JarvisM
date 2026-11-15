"""Client for the YouTube-only JARVIS Chrome extension."""
import json
import os
import platform
import re
import socket
import tempfile
from pathlib import Path


def socket_path():
    if platform.system() != 'Linux':
        raise RuntimeError('La integración de Chrome está disponible solo en Linux.')
    directory = Path(tempfile.gettempdir()) / ('jarvis-chrome-' + str(os.getuid()))
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise RuntimeError('No se pudo verificar el canal de Chrome.')
    os.chmod(directory, 0o700)
    return directory / 'music.sock'


def command(action, video_id=None, start=False):
    if action not in ('open', 'pause') or (action == 'open' and
            (not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id))):
        return {'error': 'Solicitud de música inválida.'}
    try:
        # Register the narrowly scoped native host automatically on first use.
        # Chrome must still have the extension installed and enabled.
        from install_chrome_music import install
        install(quiet=True)
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(55)
            client.connect(str(socket_path()))
            client.sendall(json.dumps({'action': action, 'video_id': video_id}).encode() + b'\n')
            buf = bytearray()
            while b'\n' not in buf and len(buf) < 8192:
                chunk = client.recv(4096)
                if not chunk:
                    break
                buf.extend(chunk)
            result = json.loads(buf.split(b'\n', 1)[0])
            if not isinstance(result, dict):
                raise ValueError('Invalid result')
            return result
    except (OSError, ValueError, RuntimeError):
        return {'error': 'Chrome no está conectado a JARVIS. Abre Chrome y activa la extensión JARVIS Música.'}
