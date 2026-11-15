#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo 'Instale Python 3.11 o superior.'; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 o superior es obligatorio"'
python3 -m venv venv
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements.txt
if [[ ! -f .env ]]; then
  read -r -s -p 'Introduzca GEMINI_API_KEY (no se mostrará): ' key; echo
  if [[ -z "$key" || "$key" == *$'\n'* || "$key" == *$'\r'* ]]; then echo 'Clave inválida.'; exit 1; fi
  # Gemini keys do not contain shell quoting characters. Reject them rather than writing unsafe dotenv syntax.
  if [[ ! "$key" =~ ^[A-Za-z0-9_-]+$ ]]; then echo 'Formato de clave inválido.'; exit 1; fi
  (umask 077; printf 'GEMINI_API_KEY=%s\n' "$key" > .env)
  unset key
fi
venv/bin/python desktop_launcher.py || echo 'No se pudo crear el acceso directo; puedes intentarlo después.'
echo 'Instalación terminada. Abre JARVIS desde el escritorio o el menú de aplicaciones.'
