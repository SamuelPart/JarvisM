#!/usr/bin/env bash
# =============================================================================
# JarvisM · instalador para macOS (Intel y Apple Silicon)
#
#   ./scripts/install-macos.sh            # instalación estándar
#   ./scripts/install-macos.sh --voice    # añade STT/TTS locales
#   ./scripts/install-macos.sh --all      # todos los extras
#
# Requiere Homebrew (https://brew.sh). Si no lo tienes, el script lo explica y
# continúa con lo que haya disponible.
# =============================================================================
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_DIR}/.venv"

WANT_VOICE=0
WANT_UI=0
WANT_DEV=0

if [[ -t 1 ]]; then
  C_OK=$'\033[0;32m'; C_WARN=$'\033[0;33m'; C_ERR=$'\033[0;31m'; C_DIM=$'\033[2m'; C_OFF=$'\033[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_DIM=""; C_OFF=""
fi
step() { printf '%s==>%s %s\n' "${C_OK}" "${C_OFF}" "$*"; }
warn() { printf '%s[aviso]%s %s\n' "${C_WARN}" "${C_OFF}" "$*" >&2; }
die()  { printf '%s[error]%s %s\n' "${C_ERR}" "${C_OFF}" "$*" >&2; exit 1; }
note() { printf '%s    %s%s\n' "${C_DIM}" "$*" "${C_OFF}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --voice) WANT_VOICE=1 ;;
    --ui)    WANT_UI=1 ;;
    --dev)   WANT_DEV=1 ;;
    --all)   WANT_VOICE=1; WANT_UI=1; WANT_DEV=1 ;;
    --no-system) SKIP_BREW=1 ;;
    -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "opción desconocida: $1" ;;
  esac
  shift
done

step "Comprobando el entorno"
[[ "$(uname -s)" == "Darwin" ]] || die "este script es para macOS. En Linux usa scripts/install-kali.sh"
[[ "${EUID}" -ne 0 ]] || die "no ejecutes JarvisM como root (docs/03 §1)"

PYTHON_BIN="${PYTHON_BIN:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "no encuentro python3. brew install python@3.12"
note "$("$PYTHON_BIN" --version)"

if [[ "${SKIP_BREW:-0}" -eq 0 ]]; then
  if command -v brew >/dev/null 2>&1; then
    step "Instalando utilidades con Homebrew"
    brew list --formula >/dev/null 2>&1 || true
    BREW_PKGS=(python@3.12 git)
    (( WANT_VOICE )) && BREW_PKGS+=(portaudio libsndfile ffmpeg)
    # brightness: control de brillo desde línea de comandos
    BREW_PKGS+=(brightness)
    for pkg in "${BREW_PKGS[@]}"; do
      brew list "$pkg" >/dev/null 2>&1 || brew install "$pkg" || warn "no pude instalar $pkg"
    done
  else
    warn "no hay Homebrew: instala las dependencias manualmente (https://brew.sh)"
    note "necesarias: python@3.12, git"
  fi
else
  step "Omitiendo Homebrew (--no-system)"
fi

cd "$REPO_DIR"
step "Creando el entorno virtual"
[[ -d "$VENV_DIR" ]] || "$PYTHON_BIN" -m venv "$VENV_DIR"
# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
python -m pip install --quiet --upgrade pip wheel

step "Instalando JarvisM"
EXTRAS=""
(( WANT_VOICE )) && EXTRAS="${EXTRAS},voice"
(( WANT_UI ))    && EXTRAS="${EXTRAS},ui"
(( WANT_DEV ))   && EXTRAS="${EXTRAS},dev"
EXTRAS="${EXTRAS#,}"
if [[ -n "$EXTRAS" ]]; then
  pip install --quiet -e ".[${EXTRAS}]"
else
  pip install --quiet -e .
fi

step "Preparando la configuración"
if [[ ! -f "${REPO_DIR}/.env" ]]; then
  cp "${REPO_DIR}/.env.example" "${REPO_DIR}/.env"
  chmod 600 "${REPO_DIR}/.env"
  note "creado .env (permisos 600)"
fi

step "Diagnóstico"
set +e; jarvis doctor; STATUS=$?; set -e

cat <<EOF

${C_OK}Instalación terminada${C_OFF}

  1. source ${VENV_DIR}/bin/activate
  2. nano ${REPO_DIR}/.env
  3. jarvis doctor --providers
  4. jarvis chat

${C_WARN}Permisos en macOS${C_OFF}: para controlar ventanas, notificaciones y micrófono,
concede Accesibilidad y Grabación de pantalla a tu terminal en
Ajustes del Sistema → Privacidad y seguridad.
${C_DIM}jarvis doctor te dirá exactamente cuáles faltan.${C_OFF}
EOF
exit $(( STATUS != 0 ))
