"""Diagnóstico del entorno: la implementación de `jarvis doctor`.

Devuelve una lista de `Check` con nivel ok/warn/fail. Nunca lanza excepciones:
el doctor tiene que funcionar precisamente cuando el entorno está roto.
"""

from __future__ import annotations

import getpass
import os
import platform
import shutil
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis import __version__
from jarvis.config.settings import Settings
from jarvis.platforms.base import OSAdapter
from jarvis.platforms.factory import detect_platform

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_FAIL = "fail"


@dataclass(slots=True)
class Check:
    name: str
    level: str
    detail: str
    hint: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "level": self.level, "detail": self.detail, "hint": self.hint}


@dataclass(slots=True)
class DiagnosticReport:
    checks: list[Check] = field(default_factory=list)
    platform: str = ""
    version: str = __version__

    def add(self, name: str, level: str, detail: str, hint: str = "") -> Check:
        check = Check(name, level, detail, hint)
        self.checks.append(check)
        return check

    @property
    def ok(self) -> bool:
        return not any(c.level == LEVEL_FAIL for c in self.checks)

    @property
    def warnings(self) -> int:
        return sum(1 for c in self.checks if c.level == LEVEL_WARN)

    @property
    def failures(self) -> int:
        return sum(1 for c in self.checks if c.level == LEVEL_FAIL)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "platform": self.platform,
            "ok": self.ok,
            "warnings": self.warnings,
            "failures": self.failures,
            "checks": [c.to_dict() for c in self.checks],
        }


# --------------------------------------------------------------------------- #
def run_diagnostics(settings: Settings, adapter: OSAdapter, *, providers: bool = False) -> DiagnosticReport:
    report = DiagnosticReport(platform=f"{detect_platform().value} · {platform.platform()}")

    # --- Python y entorno ------------------------------------------------ #
    version = sys.version_info
    if version >= (3, 11):
        report.add("python", LEVEL_OK, f"{platform.python_version()}")
    elif version >= (3, 10):
        report.add(
            "python",
            LEVEL_WARN,
            f"{platform.python_version()}",
            "funciona, pero 3.11+ trae mejoras de rendimiento y de asyncio",
        )
    else:
        report.add("python", LEVEL_FAIL, f"{platform.python_version()}", "JarvisM requiere Python 3.10+")

    in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    report.add(
        "entorno virtual",
        LEVEL_OK if in_venv else LEVEL_WARN,
        sys.prefix,
        ""
        if in_venv
        else "no estás en un venv; en Debian/Kali el Python del sistema está protegido (PEP 668)",
    )

    is_admin = _is_privileged()
    report.add(
        "privilegios",
        LEVEL_FAIL if is_admin else LEVEL_OK,
        f"usuario {getpass.getuser()} (uid={_uid()})",
        "JarvisM no debe ejecutarse como root/administrador (docs/03 §1)" if is_admin else "",
    )

    # --- Dependencias opcionales ----------------------------------------- #
    optional = {
        "sounddevice": (
            "voz: captura de audio",
            "sudo apt install portaudio19-dev && pip install -e '.[voice]'",
        ),
        "faster_whisper": ("voz: STT local", "pip install -e '.[voice]'"),
        "piper": ("voz: TTS local", "pip install -e '.[voice]'"),
        "fastapi": ("servidor web/HUD", "pip install -e '.[ui]'"),
        "numpy": ("procesado de audio", "pip install numpy"),
    }
    for module, (what, hint) in optional.items():
        report.add(
            f"extra {module}",
            LEVEL_OK if _importable(module) else LEVEL_WARN,
            "instalado" if _importable(module) else f"no instalado ({what})",
            "" if _importable(module) else hint,
        )

    # --- Capacidades de plataforma --------------------------------------- #
    for cap in adapter.capabilities():
        report.add(
            f"capacidad:{cap.name}",
            LEVEL_OK if cap.available else LEVEL_WARN,
            cap.backend or ("disponible" if cap.available else "no disponible"),
            cap.hint,
        )

    # --- Permisos y rutas ------------------------------------------------- #
    settings.ensure_dirs()
    writable = os.access(settings.data_dir, os.W_OK)
    mode = _mode(settings.data_dir)
    report.add(
        "directorio de datos",
        LEVEL_OK if writable else LEVEL_FAIL,
        f"{settings.data_dir} (permisos {mode})",
        "" if writable else "sin permiso de escritura",
    )
    if mode not in {"700", "0700"} and mode:
        report.add("permisos de datos", LEVEL_WARN, mode, "debería ser 700: contiene auditoría y memoria")

    env_file = Path.cwd() / ".env"
    if env_file.exists():
        env_mode = _mode(env_file)
        report.add(
            "archivo .env",
            LEVEL_OK if env_mode in {"600", "0600"} else LEVEL_WARN,
            f"{env_file} (permisos {env_mode})",
            "" if env_mode in {"600", "0600"} else "ejecuta: chmod 600 .env",
        )
    else:
        report.add(
            "archivo .env",
            LEVEL_WARN,
            "no encontrado en el directorio actual",
            "cp .env.example .env && chmod 600 .env",
        )

    # --- Proveedores ------------------------------------------------------ #
    from jarvis.providers.registry import ProviderRegistry

    registry = ProviderRegistry.from_settings(settings)
    any_key = False
    for name in registry.names:
        provider = registry.get(name)
        if provider is None:
            continue
        available, reason = provider.available()
        if name == "echo":
            report.add(f"proveedor:{name}", LEVEL_OK, "siempre disponible (sin IA, para pruebas)")
            continue
        if name == "ollama":
            reachable = _port_open(provider.base_url)
            report.add(
                f"proveedor:{name}",
                LEVEL_OK if reachable else LEVEL_WARN,
                provider.base_url + (" responde" if reachable else " no responde"),
                "" if reachable else "arranca Ollama (`ollama serve`) o ignora este aviso",
            )
            continue
        if available:
            any_key = True
            key = provider.api_key or ""
            report.add(f"proveedor:{name}", LEVEL_OK, f"clave presente (…{key[-4:]})")
        else:
            report.add(f"proveedor:{name}", LEVEL_WARN, reason, "consigue la clave y ponla en .env (docs/05)")
    report.add(
        "modo de operación",
        LEVEL_OK if any_key or _ollama_alive(settings) else LEVEL_WARN,
        "online (hay al menos una clave)"
        if any_key
        else "solo local: sin claves, Jarvis usará el matcher determinista y el proveedor echo",
        "" if any_key else "para conversación real necesitas una clave o Ollama con un modelo descargado",
    )

    # --- Integridad de la auditoría --------------------------------------- #
    if settings.audit_db.exists():
        try:
            from jarvis.safety.audit import AuditLog

            audit = AuditLog(settings.audit_db)
            valid, message = audit.verify()
            entries = audit.count()
            audit.close()
            report.add(
                "audit log",
                LEVEL_OK if valid else LEVEL_FAIL,
                f"{message}",
                "" if valid else "la cadena está rota: revisa quién modificó el fichero",
            )
            report.add("audit log (tamaño)", LEVEL_OK, f"{entries} entradas en {settings.audit_db}")
        except sqlite3.Error as exc:
            report.add(
                "audit log",
                LEVEL_FAIL,
                f"no se pudo abrir: {exc}",
                "si está corrupto: muévelo aparte y Jarvis creará uno nuevo",
            )
    else:
        report.add("audit log", LEVEL_OK, "aún no existe (se crea con la primera acción)")

    # --- Configuración ----------------------------------------------------- #
    report.add("capas de configuración", LEVEL_OK, " ← ".join(settings.sources) or "solo defaults")
    budget = settings.budget
    report.add(
        "presupuesto diario",
        LEVEL_OK if budget.usd_per_day > 0 else LEVEL_WARN,
        f"{budget.usd_per_day:.2f} USD/día · {budget.tokens_per_day:,} tokens",
        "" if budget.usd_per_day > 0 else "sin límite de gasto: no recomendado",
    )
    report.add(
        "auto-approve máximo",
        LEVEL_OK,
        settings.policy.auto_approve_max_tier,
        "los tiers por encima pedirán confirmación siempre",
    )

    # --- Salud real de los proveedores (opt-in: hace llamadas de red) ------- #
    if providers:
        import asyncio

        from jarvis.core.router import Router

        router = Router(settings, registry=registry)
        health = asyncio.run(router.health(force=True))
        for name, info in health.items():
            report.add(
                f"health:{name}",
                LEVEL_OK if info["ok"] else LEVEL_WARN,
                f"{info['reason']} ({info['latency_ms']} ms)" if info["ok"] else info["reason"],
                "" if info["ok"] else "revisa la clave, el modelo configurado y tu cuota",
            )
        asyncio.run(router.aclose())

    return report


# --------------------------------------------------------------------------- #
def _importable(module: str) -> bool:
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def _is_privileged() -> bool:
    if sys.platform == "win32":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except Exception:
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _uid() -> int:
    return os.geteuid() if hasattr(os, "geteuid") else -1


def _mode(path: Path) -> str:
    try:
        return format(path.stat().st_mode & 0o777, "o")
    except OSError:
        return ""


def _port_open(url: str) -> bool:
    """Comprueba si un endpoint HTTP local responde, sin dependencias."""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=1.5):
            return True
    except OSError:
        return False


def _ollama_alive(settings: Settings) -> bool:
    return _port_open(settings.providers.ollama.base_url or "http://127.0.0.1:11434")


def tool_availability() -> dict[str, str | None]:
    """Utilidad para tests y para el doctor: binarios externos detectados."""
    names = [
        "wmctrl",
        "xdotool",
        "xclip",
        "wl-copy",
        "notify-send",
        "pactl",
        "wpctl",
        "brightnessctl",
        "playerctl",
        "gio",
        "sensors",
        "apt-get",
        "ffmpeg",
        "ollama",
    ]
    return {n: shutil.which(n) for n in names}
