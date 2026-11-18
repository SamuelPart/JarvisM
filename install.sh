#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo 'Instale Python 3.11 o superior.'; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 o superior es obligatorio"'
python3 -m venv venv
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements.txt
if [[ ! -f .env ]]; then
  read -r -s -p 'NVIDIA_API_KEY (tu clave; Enter para omitir y usar el proxy del desarrollador): ' key; echo
  if [[ -z "$key" ]]; then
    echo 'Sin clave: JARVIS usará el proxy del desarrollador (si tu build lo trae configurado).'
  else
    if [[ "$key" == *$'\n'* || "$key" == *$'\r'* ]]; then echo 'Clave inválida.'; exit 1; fi
    # NVIDIA keys (nvapi-...) do not contain shell quoting characters. Reject them rather than writing unsafe dotenv syntax.
    if [[ ! "$key" =~ ^[A-Za-z0-9_-]+$ ]]; then echo 'Formato de clave inválido.'; exit 1; fi
    (umask 077; printf 'NVIDIA_API_KEY=%s\n' "$key" > .env)
  fi
  unset key
fi
venv/bin/python desktop_launcher.py || echo 'No se pudo crear el acceso directo; puedes intentarlo después.'
echo 'Instalación terminada. Abre JARVIS desde el escritorio o el menú de aplicaciones.'
