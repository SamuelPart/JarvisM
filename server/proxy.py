#!/usr/bin/env python3
"""JARVIS relay — developer-hosted proxy in front of NVIDIA NIM.

End users of a developer-built JARVIS install and run with NO API key:
the desktop client talks to this relay, and the relay holds the developer's
NVIDIA_API_KEY server-side. It is a narrow relay, not a general proxy:

  * only POST /v1/chat/completions is forwarded (to NVIDIA),
  * the requested model must be in ALLOWED_MODELS (default: the JARVIS default),
  * max_tokens is capped, total prompt characters are capped,
  * per-client-IP rate limits per minute and per day,
  * optional shared client token (JARVIS_PROXY_TOKEN) enforced as Bearer auth,
  * upstream error bodies are NOT relayed verbatim to clients (no key/model leakage);
    only the status code is preserved.

Honest limitations:
  * Rate limiting is in-memory and per-process: limits reset on restart and
    do NOT aggregate across multiple workers/instances. One instance is fine
    to start; scale behind nginx with a shared store before real traffic.
  * Client IP limiting trusts request.client.host. Behind a reverse proxy,
    make sure nginx sets X-Forwarded-For and run uvicorn with
    --proxy-headers, or the relay will see only the proxy's address.
    (Avoid trusting client-supplied X-Forwarded-For directly — set it in nginx.)
  * Prompts of your users DO transit this server (as they do any API relay).
    Tell your users; log nothing conversationally.
  * You pay the NVIDIA quota of everyone using your build. Watch usage.

Environment:
  NVIDIA_API_KEY          (required, server-side only)
  DEFAULT_MODEL           default model when the client omits it
  ALLOWED_MODELS          comma-separated allowlist (default: DEFAULT_MODEL)
  MAX_TOKENS_CAP          max_tokens cap per request (default 1024)
  MESSAGES_CHAR_CAP       total characters budget per request (default 24000)
  RATE_LIMIT_PER_MINUTE   per-IP requests per minute (default 6)
  RATE_LIMIT_PER_DAY      per-IP requests per day (default 100)
  JARVIS_PROXY_TOKEN      optional Bearer token clients must present
  UPSTREAM_TIMEOUT        seconds for the NVIDIA call (default 60)

Run behind TLS (nginx/Caddy). See server/README.md. Do not expose directly
to the internet without TLS.
"""
import hmac
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

NVIDIA_URL = 'https://integrate.api.nvidia.com/v1/chat/completions'
DEFAULT_MODEL = os.getenv('DEFAULT_MODEL', 'nvidia/nemotron-3.5-bolt-e4b')
ALLOWED_MODELS = {m.strip() for m in os.getenv('ALLOWED_MODELS', DEFAULT_MODEL).split(',') if m.strip()}
MAX_TOKENS_CAP = int(os.getenv('MAX_TOKENS_CAP', '1024'))
MESSAGES_CHAR_CAP = int(os.getenv('MESSAGES_CHAR_CAP', '24000'))
PER_MINUTE = int(os.getenv('RATE_LIMIT_PER_MINUTE', '6'))
PER_DAY = int(os.getenv('RATE_LIMIT_PER_DAY', '100'))
UPSTREAM_KEY = os.getenv('NVIDIA_API_KEY', '').strip()
CLIENT_TOKEN = os.getenv('JARVIS_PROXY_TOKEN', '').strip()
UPSTREAM_TIMEOUT = float(os.getenv('UPSTREAM_TIMEOUT', '60'))
MAX_BODY_BYTES = 256 * 1024

MINUTE = 60.0
DAY = 86400.0

app = FastAPI(title='jarvis-relay', docs_url=None, redoc_url=None, openapi_url=None)

_hits = defaultdict(deque)          # ip -> timestamps (sliding window, last day retained)


def _allow(ip: str) -> bool:
    now = time.time()
    dq = _hits[ip]
    while dq and now - dq[0] > DAY:
        dq.popleft()
    minute = sum(1 for t in dq if now - t < MINUTE)
    if minute >= PER_MINUTE or len(dq) >= PER_DAY:
        return False
    dq.append(now)
    return True


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else 'unknown'


@app.get('/healthz')
def healthz():
    return {'ok': True}


@app.post('/v1/chat/completions')
async def chat_completions(request: Request):
    if not UPSTREAM_KEY:
        return JSONResponse({'error': 'relay not configured'}, status_code=500)
    if CLIENT_TOKEN:
        auth = request.headers.get('authorization', '')
        expected = 'Bearer ' + CLIENT_TOKEN
        if not hmac.compare_digest(auth.encode(), expected.encode()):
            return JSONResponse({'error': 'unauthorized'}, status_code=401)
    content_length = request.headers.get('content-length')
    if content_length and int(content_length) > MAX_BODY_BYTES:
        return JSONResponse({'error': 'body too large'}, status_code=413)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({'error': 'invalid JSON'}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({'error': 'invalid JSON'}, status_code=400)
    model = body.get('model') or DEFAULT_MODEL
    if ALLOWED_MODELS and model not in ALLOWED_MODELS:
        return JSONResponse({'error': 'model not allowed'}, status_code=400)
    messages = body.get('messages')
    if not isinstance(messages, list) or not messages or len(messages) > 64:
        return JSONResponse({'error': 'messages must be a list of 1..64 items'}, status_code=400)
    total_chars = sum(len(str(m.get('content') or '')) for m in messages if isinstance(m, dict))
    if total_chars > MESSAGES_CHAR_CAP:
        return JSONResponse({'error': 'prompt too large'}, status_code=400)
    ip = _client_ip(request)
    if not _allow(ip):
        return JSONResponse({'error': 'rate limit exceeded'}, status_code=429, headers={'Retry-After': '60'})
    try:
        max_tokens = min(int(body.get('max_tokens', MAX_TOKENS_CAP)), MAX_TOKENS_CAP)
    except (TypeError, ValueError):
        max_tokens = MAX_TOKENS_CAP
    payload = dict(body)
    payload.update({'model': model, 'max_tokens': max_tokens, 'stream': False})
    try:
        upstream = requests.post(NVIDIA_URL,
                                 headers={'Authorization': 'Bearer ' + UPSTREAM_KEY,
                                          'Accept': 'application/json'},
                                 json=payload, timeout=UPSTREAM_TIMEOUT)
    except requests.RequestException:
        return JSONResponse({'error': 'upstream unreachable'}, status_code=502)
    try:
        upstream.json()
    except ValueError:
        return JSONResponse({'error': 'bad upstream response'}, status_code=502)
    # Preserve the upstream status code but do not relay arbitrary bodies on hard failures.
    if 200 <= upstream.status_code < 300:
        return Response(content=upstream.content, status_code=upstream.status_code,
                        media_type='application/json')
    return JSONResponse({'error': 'upstream rejected the request'}, status_code=upstream.status_code)
