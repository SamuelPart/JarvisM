#!/usr/bin/env bash
# =============================================================================
# JarvisM · instalador para Kali Linux / Debian (y derivados con apt)
#
# Diseñado para ser IDEMPOTENTE: puedes ejecutarlo varias veces sin romper nada.
# Nunca instala nada de Python en el sistema (PEP 668): todo va a .venv.
#
#   ./scripts/install-kali.sh              # instalación estándar
#   ./scripts/install-kali.sh --voice      # añade STT/TTS locales (más pesado)
#   ./scripts/install-kali.sh --ui         # añade FastAPI para el HUD (Fase 6)
#   ./scripts/install-kali.sh --all        # voice + ui + dev
#   ./scripts/install-kali.sh --no-system  # no toca apt (si ya tienes lo necesario)
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_DIR}/.venv"

WANT_VOICE=0
WANT_UI=0
WANT_DEV=0
DO_SYSTEM=1
PYTHON_BIN="${PYTHON_BIN:-python3}"

# --------------------------------------------------------------------------- #
# Utilidades de salida
# --------------------------------------------------------------------------- #
if [[ -t 1 ]]; then
  C_OK=$'\033[0;32m'; C_WARN=$'\033[0;33m'; C_ERR=$'\033[0;31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_DIM=""; C_OFF=""
fi
step() { printf '%s==>%s %s\n' "${C_OK}" "${C_OFF}" "$*"; }
warn() { printf '%s[aviso]%s %s\n' "${C_WARN}" "${C_OFF}" "$*" >&2; }
die()  { printf '%s[error]%s %s\n' "${C_ERR}" "${C_OFF}" "$*" >&2; exit 1; }
note() { printf '%s    %s%s\n' "${C_DIM}" "$*" "${C_OFF}"; }

# --------------------------------------------------------------------------- #
# Guardarraíl de directorio de trabajo
# --------------------------------------------------------------------------- #
# Un shell atrapado dentro de un directorio BORRADO rompe cualquier comando con
# "No such file or directory" (hasta un `touch`), pero el prompt sigue mostrando
# `[~/JarvisM]`, así que parece que el culpable es el repo o el clon. Detectarlo
# convierte media hora de confusión en un aviso de una línea. Ojo: `cd .` NO sirve
# como test (bash lo permite en un cwd borrado); `[[ -d $PWD ]]` sí.
if [[ ! -d "${PWD}" ]]; then
  warn "tu directorio actual (${PWD}) ya no existe: esa es la causa de los errores"
  warn "'No such file or directory' en comandos que antes funcionaban"
  cd "${HOME:-/tmp}" || die "no se puede acceder ni a \$HOME"
  note "seguimos desde ${PWD}; el instalador trabaja con rutas absolutas"
fi

# --------------------------------------------------------------------------- #
# Argumentos
# --------------------------------------------------------------------------- #
while [[ $# -gt 0 ]]; do
  case "$1" in
    --voice)    WANT_VOICE=1 ;;
    --ui)       WANT_UI=1 ;;
    --dev)      WANT_DEV=1 ;;
    --all)      WANT_VOICE=1; WANT_UI=1; WANT_DEV=1 ;;
    --no-system) DO_SYSTEM=0 ;;
    -h|--help)
      sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) die "opción desconocida: $1 (usa --help)" ;;
  esac
  shift
done

# --------------------------------------------------------------------------- #
# 0. Comprobaciones previas
# --------------------------------------------------------------------------- #
step "Comprobando el entorno"

[[ "$(uname -s)" == "Linux" ]] || die "este script es para Linux. En macOS usa scripts/install-macos.sh"

if [[ "${EUID}" -eq 0 ]]; then
  die "no ejecutes JarvisM como root. Crea un usuario normal y trabaja desde ahí (docs/03 §1)."
fi

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "no encuentro $PYTHON_BIN. sudo apt install python3 python3-venv"

PY_MAJOR="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.major)')"
PY_MINOR="$("$PYTHON_BIN" -c 'import sys; print(sys.version_info.minor)')"
if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 10) )); then
  die "se necesita Python 3.10+; tienes ${PY_MAJOR}.${PY_MINOR}"
fi
note "Python ${PY_MAJOR}.${PY_MINOR} detectado"

# --------------------------------------------------------------------------- #
# 1. Dependencias del sistema
# --------------------------------------------------------------------------- #
if (( DO_SYSTEM )); then
  step "Instalando dependencias del sistema (requiere sudo)"
  if command -v apt >/dev/null 2>&1; then
    SUDO=""
    [[ "${EUID}" -ne 0 ]] && SUDO="sudo"
    PKGS=(
      python3 python3-venv python3-dev python3-pip
      git curl build-essential
      # Escritorio: ventanas, notificaciones, portapapeles, audio, brillo, media
      wmctrl xdotool xclip libnotify-bin brightnessctl playerctl
      # Utilidades que usan los monitores del watchdog
      lsof
    )
    if (( WANT_VOICE )); then
      PKGS+=(portaudio19-dev libsndfile1 ffmpeg espeak-ng)
    fi
    $SUDO apt-get update -qq
    $SUDO apt-get install -y --no-install-recommends "${PKGS[@]}"
    note "paquetes instalados: ${#PKGS[@]}"
    note "opcional recomendado: sudo apt install lm-sensors smartmontools && sudo sensors-detect --auto"
  else
    warn "no encuentro apt: instala a mano wmctrl, xdotool, xclip, libnotify-bin, brightnessctl"
  fi
else
  step "Omitiendo dependencias del sistema (--no-system)"
fi

# --------------------------------------------------------------------------- #
# 2. Entorno virtual
# --------------------------------------------------------------------------- #
cd "$REPO_DIR"
step "Creando el entorno virtual en ${VENV_DIR}"
if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python -m pip install --quiet --upgrade pip wheel

# --------------------------------------------------------------------------- #
# 3. JarvisM y extras
# --------------------------------------------------------------------------- #
step "Instalando JarvisM (editable)"
EXTRAS=""
(( WANT_VOICE )) && EXTRAS="${EXTRAS},voice"
(( WANT_UI ))    && EXTRAS="${EXTRAS},ui"
(( WANT_DEV ))   && EXTRAS="${EXTRAS},dev"
EXTRAS="${EXTRAS#,}"

if [[ -n "$EXTRAS" ]]; then
  pip install --quiet -e ".[${EXTRAS}]"
  note "extras instalados: ${EXTRAS}"
else
  pip install --quiet -e .
fi

# --------------------------------------------------------------------------- #
# 4. Configuración inicial
# --------------------------------------------------------------------------- #
step "Preparando la configuración"
if [[ ! -f "${REPO_DIR}/.env" ]]; then
  cp "${REPO_DIR}/.env.example" "${REPO_DIR}/.env"
  chmod 600 "${REPO_DIR}/.env"
  note "creado .env (permisos 600). Edítalo y añade al menos una clave."
else
  chmod 600 "${REPO_DIR}/.env" || true
  note ".env ya existía; no lo he tocado"
fi

mkdir -p "$HOME/JarvisWorkspace" 2>/dev/null || true

# --------------------------------------------------------------------------- #
# 5. Verificación
# --------------------------------------------------------------------------- #
step "Ejecutando el diagnóstico"
set +e
jarvis doctor
DOCTOR_STATUS=$?
set -e

echo
if (( DOCTOR_STATUS == 0 )); then
  step "Instalación completada"
else
  warn "la instalación terminó, pero el diagnóstico encontró cosas que revisar (arriba)"
fi
cat <<EOF

${C_OK}Siguientes pasos${C_OFF}

  1. Activa el entorno:      source ${VENV_DIR}/bin/activate
  2. Añade una clave:        nano ${REPO_DIR}/.env   (GEMINI_API_KEY es gratis y sin tarjeta)
  3. Comprueba proveedores:  jarvis doctor --providers
  4. Prueba sin gastar nada: jarvis chat --provider echo
  5. Habla con él:           jarvis chat
  6. Vigilancia proactiva:   jarvis watch

${C_DIM}Guía completa con pruebas paso a paso: docs/04-guia-kali-linux.md${C_OFF}
${C_DIM}Añade 'source ${VENV_DIR}/bin/activate' a tu ~/.bashrc si quieres el comando siempre a mano.${C_OFF}
EOF
