#!/usr/bin/env python3
"""Native messaging bridge: accepts only open/pause commands from this user."""
import fcntl
import json
import os
import re
import socket
import struct
import sys
import threading
import uuid
from pathlib import Path

from chrome_music import socket_path

HOST = 'com.jarvis.music'
EXTENSION_ID = (Path(__file__).resolve().parent / 'chrome_extension' / 'extension_id.txt').read_text().strip()
MAX_NATIVE = 65536


def read_message(stream):
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ValueError('Invalid header')
    length = struct.unpack('=I', header)[0]
    if length > MAX_NATIVE:
        raise ValueError('Message too large')
    data = stream.read(length)
    if len(data) != length:
        raise ValueError('Incomplete message')
    result = json.loads(data.decode('utf-8'))
    if not isinstance(result, dict):
        raise ValueError('Invalid message')
    return result


def write_message(stream, message):
    body = json.dumps(message, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(body) > MAX_NATIVE:
        raise ValueError('Message too large')
    stream.write(struct.pack('=I', len(body)) + body)
    stream.flush()


def run(stdin, stdout):
    path = socket_path()
    lock_fd = os.open(path.parent / 'host.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(lock_fd, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(path))
        os.chmod(path, 0o600)
        server.listen(4)
        server.settimeout(0.5)
        alive = threading.Event()
        alive.set()
        ready = threading.Event()
        replies = {}
        def reader():
            try:
                while alive.is_set():
                    msg = read_message(stdin)
                    if msg is None:
                        break
                    key = msg.get('id')
                    if isinstance(key, str) and re.fullmatch(r'[0-9a-f]{32}', key):
                        replies[key] = msg.get('result')
                        ready.set()
            except (OSError, ValueError, UnicodeError):
                pass
            finally:
                alive.clear()
                ready.set()
        threading.Thread(target=reader, daemon=True).start()
        try:
            while alive.is_set():
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                with conn:
                    conn.settimeout(4)
                    try:
                        data = bytearray()
                        while b'\n' not in data and len(data) < 4096:
                            chunk = conn.recv(4096)
                            if not chunk:
                                break
                            data.extend(chunk)
                        if len(data) >= 4096:
                            raise ValueError('Request too large')
                        request = json.loads(data.split(b'\n', 1)[0])
                        action, video_id = request.get('action'), request.get('video_id')
                        if action not in ('open', 'pause') or (action == 'open' and
                                (not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id))):
                            raise ValueError('Invalid request')
                        key = uuid.uuid4().hex
                        ready.clear()
                        write_message(stdout, {'id': key, 'action': action, 'video_id': video_id})
                        ready.wait(45)
                        result = replies.pop(key, None)
                        if not isinstance(result, dict):
                            result = {'error': 'Chrome no respondió; comprueba la extensión de JARVIS.'}
                        # Pass only known status flags and brief fixed messages; never relay page data.
                        safe = {k: result[k] for k in ('opened', 'playing', 'paused') if type(result.get(k)) is bool}
                        code = result.get('code')
                        messages = {
                            'ad': 'La página muestra un anuncio; no se confirmó la canción.',
                            'youtube_error': 'YouTube muestra un error de reproducción.',
                            'not_playing': 'Se abrió YouTube, pero no se confirmó la reproducción.',
                            'no_tab': 'No hay una pestaña de música de JARVIS para pausar.',
                            'tab_error': 'No se pudo abrir o controlar la pestaña de YouTube en Chrome.',
                            'muted': 'El video está silenciado en YouTube.',
                        }
                        if code in messages:
                            safe['note' if safe.get('opened') else 'error'] = messages[code]
                        if not safe:
                            safe = {'error': 'Chrome no confirmó el resultado de la solicitud.'}
                        conn.sendall(json.dumps(safe, ensure_ascii=False).encode() + b'\n')
                    except (OSError, ValueError, TypeError, AttributeError):
                        try:
                            conn.sendall(b'{"error":"No se pudo procesar la solicitud de Chrome."}\n')
                        except OSError:
                            pass
        finally:
            alive.clear()
            server.close()
            path.unlink(missing_ok=True)


if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1].rstrip('/') != 'chrome-extension://' + EXTENSION_ID:
        sys.exit(1)
    run(sys.stdin.buffer, sys.stdout.buffer)
