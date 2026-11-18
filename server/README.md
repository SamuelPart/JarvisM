# JARVIS relay — el proxy del desarrollador

Con este pequeño servidor, **los usuarios no ponen ninguna clave**: instalan JARVIS y hablan con tu relay, que guarda **tu** `NVIDIA_API_KEY` en el servidor y reenvía a NVIDIA NIM. Sin él, cada usuario debe poner su propia clave (modo «trae tu propia clave», ver README principal).

El cliente ya soporta ambos modos: si en `.env` hay `NVIDIA_API_KEY`, se usa siempre (tu clave propia del usuario manda). Si no hay clave y el build trae `JARVIS_PROXY_URL` (o el desarrollador editó `DEFAULT_PROXY_URL` en `nvidia_brain.py`), se usa el proxy automáticamente. El usuario no configura nada.

## Honestidad primero

- **Tus usuarios te consumen tu cuota NVIDIA.** El free tier de build.nvidia.com se agota rápido; vigila el consumo y dimensiona `RATE_LIMIT_PER_MINUTE` / `RATE_LIMIT_PER_DAY` (por defecto 6/min y 100/día por IP).
- **Su prompt atraviesa este servidor** (igual que cualquier relay de IA). Comunícalo en tus ajustes de privacidad; no registres el contenido de las conversaciones.
- El límite por IP es memoria local y por proceso: se reinicia con el servicio y no suma varias instancias. Detrás de nginx pon `X-Forwarded-For` y arranca uvicorn con `--proxy-headers`.
- El proxy **no es** un proxy general: solo reenvía `POST /v1/chat/completions` con el modelo permitido y topes de tokens y caracteres.
- Un token compartido (`JARVIS_PROXY_TOKEN`) solo frena a extraños casuales: cualquier quien tenga una copia del cliente puede leerlo. Es comodidad, no seguridad real. Lo que protege tu cuota son los límites y supervisar.
- Sin TLS no lo expongas a Internet.

## Instalación (Linux, sobre un VPS o tu máquina fija)

```bash
cd server
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
cp .env.example .env   # edita: NVIDIA_API_KEY=nvapi-...
chmod 600 .env
set -a; . ./.env; set +a
./.venv/bin/uvicorn proxy:app --host 127.0.0.1 --port 8787
```

nginx delante (TLS real; ejemplo mínimo):

```nginx
server {
    listen 443 ssl;
    server_name jarvis.example.com;
    # ssl_certificate / ssl_certificate_key …
    location / {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 90s;
    }
}
```

y uvicorn con `--proxy-headers` si tu nginx está en la misma máquina.

`systemd` (para que arranque solo):

```ini
[Unit]
Description=JARVIS relay
After=network.target

[Service]
WorkingDirectory=/opt/jarvis/server
EnvironmentFile=/opt/jarvis/server/.env
ExecStart=/opt/jarvis/server/.venv/bin/uvicorn proxy:app --host 127.0.0.1 --port 8787 --proxy-headers
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

## Variables

| Variable | Defecto | Para qué |
|---|---|---|
| `NVIDIA_API_KEY` | — | **Obligatoria.** La tuya; nunca sale del servidor. |
| `DEFAULT_MODEL` | `nvidia/nemotron-3.5-bolt-e4b` | Modelo si el cliente no envía uno. |
| `ALLOWED_MODELS` | el `DEFAULT_MODEL` | Lista blanca separada por comas. |
| `MAX_TOKENS_CAP` | `1024` | Tope por petición. |
| `MESSAGES_CHAR_CAP` | `24000` | Tope de caracteres del prompt por petición. |
| `RATE_LIMIT_PER_MINUTE` | `6` | Peticiones por minuto por IP. |
| `RATE_LIMIT_PER_DAY` | `100` | Peticiones por día por IP. |
| `JARVIS_PROXY_TOKEN` | vacío | Si se define, el cliente debe enviarlo como Bearer (o pon `JARVIS_PROXY_TOKEN` también en el `.env` del build/los usuarios). |
| `UPSTREAM_TIMEOUT` | `60` | Segundos al llamar a NVIDIA. |

## Cómo enchufar el cliente

- Build de desarrollador: en `nvidia_brain.py`, edita `DEFAULT_PROXY_URL='https://jarvis.example.com/v1/chat/completions'` antes de empaquetar; o distribuye un `.env` con `JARVIS_PROXY_URL=...`. Las copias así configuradas funcionan sin tocar nada más.
- Usuario avanzado: puede ignorar el proxy poniendo su propia `NVIDIA_API_KEY` en `.env` (tiene prioridad sobre el proxy).

## Comprobación

```bash
curl -s http://127.0.0.1:8787/healthz        # {"ok":true}
curl -s -X POST http://127.0.0.1:8787/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"messages":[{"role":"user","content":"di hola"}]}'
```
