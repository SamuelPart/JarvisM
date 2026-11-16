"""Cuerpo — REST surface for the assistant (opt-in, localhost by default).

Never auto-started. Run manually:  python -m agent.server [--port 8799] [--host 127.0.0.1]

Endpoints (JSON only, max body 64 KB):
  GET  /status  → {ok, version, uptime_seconds, tools}
  POST /action  → {tool, args, confirmed?} → registry.execute(...)

Security: a bearer token is required for /action (and /status is harmless).
The token is read from JARVIS_REST_TOKEN or generated once into
.agent-memory/rest-token (chmod 600). Destructive tools additionally require
"confirmed": true in the JSON body — the token alone is not consent.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import stat
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agent import __version__
from agent.tools import build_default_registry

_STARTED = time.time()
_STATE_DIR = Path(__file__).resolve().parent.parent / '.agent-memory'
_TOKEN_FILE = _STATE_DIR / 'rest-token'


def load_or_create_token():
    env = os.environ.get('JARVIS_REST_TOKEN')
    if env:
        return env
    try:
        existing = _TOKEN_FILE.read_text(encoding='utf-8').strip()
        if existing:
            return existing
    except OSError:
        pass
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    _TOKEN_FILE.write_text(token + '\n', encoding='utf-8')
    try:
        os.chmod(_TOKEN_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 600
    except OSError:
        pass
    return token


def make_handler(registry, token):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'JarvisAgent/0.1'

        def log_message(self, *args):
            pass  # nothing sensitive to log; silence access logs

        def _send(self, code, payload):
            body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _auth_ok(self):
            header = self.headers.get('Authorization', '')
            provided = header[7:].strip() if header.startswith('Bearer ') else self.headers.get('X-Token', '')
            return bool(provided) and secrets.compare_digest(provided, token)

        def do_GET(self):
            if self.path == '/status':
                return self._send(200, {'ok': True, 'version': __version__,
                                        'uptime_seconds': round(time.time() - _STARTED, 1),
                                        'tools': [tool['name'] for tool in registry.list()]})
            return self._send(404, {'error': 'Not found'})

        def do_POST(self):
            if self.path != '/action':
                return self._send(404, {'error': 'Not found'})
            if not self._auth_ok():
                return self._send(401, {'error': 'Token requerido (Authorization: Bearer …).'})
            try:
                length = min(int(self.headers.get('Content-Length', '0')), 65536)
                body = json.loads(self.rfile.read(length) or b'{}')
                assert isinstance(body, dict)
            except (ValueError, AssertionError):
                return self._send(400, {'error': 'JSON inválido o de más de 64 KB.'})
            tool, args, confirmed = body.get('tool'), body.get('args') or {}, bool(body.get('confirmed'))
            if not isinstance(tool, str) or not tool:
                return self._send(400, {'error': 'Indica "tool".'})
            if not isinstance(args, dict):
                return self._send(400, {'error': '"args" debe ser un objeto.'})
            return self._send(200, registry.execute(tool, args, confirmed=confirmed))

    return Handler


def serve(host='127.0.0.1', port=8799, registry=None):
    registry = registry or build_default_registry()
    token = load_or_create_token()
    server = ThreadingHTTPServer((host, port), make_handler(registry, token))
    print(f'JARVIS REST escuchando en http://{host}:{port} (token en .agent-memory/rest-token o JARVIS_REST_TOKEN)')
    print('POST /action requiere token y, para herramientas peligrosas, "confirmed": true.')
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1', help='127.0.0.1 (local) o 0.0.0.0 (red); no exponer sin motivo')
    parser.add_argument('--port', type=int, default=8799)
    args = parser.parse_args()
    serve(args.host, args.port)
