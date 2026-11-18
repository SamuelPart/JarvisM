#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo 'Instale Python 3.11 o superior.'; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 o superior es obligatorio"'
python3 -m venv venv
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install -r requirements.txt
venv/bin/python desktop_launcher.py || echo 'No se pudo crear el acceso directo; puedes intentarlo después.'
echo 'Instalación terminada. Abre JARVIS y pega tu NVIDIA_API_KEY en Ajustes → Proveedor de IA.'
