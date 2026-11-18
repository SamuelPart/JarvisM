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
import whatsapp_cloud

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


def _default_message_handler():
    """Same app, same brain — not a second system.

    Reuses provider.create_brain: the same JARVIS, the same local memory. Every
    action that would ask for permission is declined remotely (approve=False);
    only actions the user already pre-authorised on this machine run.
    """
    import threading
    from provider import create_brain
    from system_control import SystemController

    brain = create_brain(SystemController(), lambda name, args: False)
    lock = threading.Lock()

    def handle(text):
        with lock:
            return brain.ask(text)

    return handle


def make_handler(registry, token, whatsapp_handler=None):
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

        def _whatsapp_webhook(self):
            try:
                length = min(int(self.headers.get('Content-Length', '0')), 65536)
                raw = self.rfile.read(length)
            except (ValueError, OSError):
                return self._send(400, {'error': 'Cuerpo inválido.'})
            if not whatsapp_cloud.verify_signature(raw, self.headers.get('X-Hub-Signature-256')):
                return self._send(503, {'error': 'Webhook rechazado: define WHATSAPP_APP_SECRET válido (X-Hub-Signature-256).'})
            try:
                payload = json.loads(raw or b'{}')
            except ValueError:
                return self._send(400, {'error': 'JSON inválido.'})
            messages = whatsapp_cloud.parse_inbound(payload)
            owner = whatsapp_cloud.recipient()
            processed = 0
            for message in messages:
                # Solo el dueño puede hablar con JARVIS por este canal; el resto se ignora en silencio.
                if not owner or message['from'] != owner:
                    continue
                handler = whatsapp_handler or _default_message_handler()
                try:
                    answer = handler(message['text'])
                except Exception:
                    answer = 'No pude procesar la solicitud.'
                if answer:
                    whatsapp_cloud.send_message(str(answer)[:4000], to=message['from'])
                processed += 1
            return self._send(200, {'status': 'ok', 'processed': processed})

        def do_GET(self):
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            if parsed.path == '/whatsapp/webhook':
                challenge = whatsapp_cloud.verify_webhook({k: v[0] for k, v in parse_qs(parsed.query).items()})
                if challenge is not None:
                    body = challenge.encode('utf-8')
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/plain; charset=utf-8')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                return self._send(403, {'error': 'Token de verificación de WhatsApp no válido.'})
            if parsed.path == '/status':
                return self._send(200, {'ok': True, 'version': __version__,
                                        'uptime_seconds': round(time.time() - _STARTED, 1),
                                        'tools': [tool['name'] for tool in registry.list()]})
            return self._send(404, {'error': 'Not found'})

        def do_POST(self):
            from urllib.parse import urlparse
            path = urlparse(self.path).path
            if path == '/whatsapp/webhook':
                return self._whatsapp_webhook()
            if path != '/action':
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


def serve(host='127.0.0.1', port=8799, registry=None, whatsapp_handler=None):
    registry = registry or build_default_registry()
    token = load_or_create_token()
    server = ThreadingHTTPServer((host, port), make_handler(registry, token, whatsapp_handler=whatsapp_handler))
    print(f'JARVIS escuchando en http://{host}:{port} (token en .agent-memory/rest-token o JARVIS_REST_TOKEN)')
    print('POST /action requiere token y, para herramientas peligrosas, "confirmed": true.')
    print('WhatsApp: GET/POST /whatsapp/webhook (requiere WHATSAPP_* en .env; solo del dueño, acciones peligrosas denegadas).')
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
