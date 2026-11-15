"""Client for the isolated, persistent music browser (Linux only)."""
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def socket_path():
    if platform.system() != 'Linux':
        raise RuntimeError('La ventana musical controlada está disponible solo en Linux.')
    directory = Path(tempfile.gettempdir()) / ('jarvis-music-' + str(os.getuid()))
    try:
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink() or directory.stat().st_uid != os.getuid():
            raise RuntimeError('No se pudo asegurar el directorio del navegador.')
        os.chmod(directory, 0o700)
    except OSError as exc:
        raise RuntimeError('No se pudo preparar el navegador musical.') from exc
    return directory / 'control-v3.sock'


def _request(path, payload, timeout):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(path))
        client.sendall(json.dumps(payload).encode('utf-8') + b'\n')
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


def command(action, video_id=None, start=False):
    try:
        path = socket_path()
        payload = {'action': action, 'video_id': video_id}
        try:
            return _request(path, payload, 110)
        except (ConnectionRefusedError, FileNotFoundError):
            if not start:
                return {'available': False}
        subprocess.Popen([sys.executable, str(ROOT / 'browser_music_worker.py')],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True, close_fds=True)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                return _request(path, payload, 110)
            except (ConnectionRefusedError, FileNotFoundError):
                time.sleep(0.1)
        return {'error': 'No se pudo iniciar la ventana controlada. Instala Playwright y Chromium y comprueba la sesión gráfica.'}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        return {'error': 'No se pudo conectar con la ventana musical controlada.'}
