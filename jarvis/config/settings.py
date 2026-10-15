"""Configuración tipada por capas.

Precedencia (menos -> más):
    defaults del paquete -> ~/.config/jarvis/config.toml -> ./jarvis.toml
    -> variables de entorno JARVIS__SECCION__CLAVE -> flags de CLI

Diseño: primero se construye un dict plano por fusión profunda de los TOML y
luego se valida una sola vez con pydantic. Así un error de configuración se
reporta al arrancar con la ruta exacta de la clave, no a mitad de ejecución.
"""

from __future__ import annotations

import contextlib
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, get_origin

import tomllib
from platformdirs import user_config_dir, user_data_dir, user_log_dir
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

APP_NAME = "jarvis"
RESOURCES = Path(__file__).resolve().parent.parent / "resources"
DEFAULT_CONFIG_PATH = RESOURCES / "config.default.toml"

# --------------------------------------------------------------------------- #
# Valores por defecto de la política de seguridad.
#
# Están duplicados a propósito con `config.default.toml` para que un `Settings()`
# construido a mano (tests, librería embebida, código de terceros) sea **igual de
# seguro** que uno cargado del TOML. Un objeto de configuración sin jaula de rutas
# ni allowlist sería una bomba de relojería.
# `tests/test_settings.py::test_model_defaults_match_toml` verifica que ambos
# lados no se separen nunca.
# --------------------------------------------------------------------------- #
DEFAULT_JAIL_ROOTS = ["~/JarvisWorkspace", "~/Documents/Jarvis", "/tmp/jarvis"]

DEFAULT_SHELL_ALLOWLIST = [
    "ls",
    "pwd",
    "cat",
    "head",
    "tail",
    "grep",
    "find",
    "du",
    "df",
    "ps",
    "top",
    "free",
    "uptime",
    "date",
    "whoami",
    "hostname",
    "uname",
    "which",
    "echo",
    "git",
    "python3",
    "pip",
    "node",
    "npm",
    "docker",
]

DEFAULT_RESTRICTED_BINARIES = [
    "sudo",
    "su",
    "doas",
    "pkexec",
    "nmap",
    "hydra",
    "sqlmap",
    "john",
    "hashcat",
    "aircrack-ng",
    "msfconsole",
    "metasploit",
    "burpsuite",
    "nikto",
    "gobuster",
    "netcat",
    "nc",
    "tcpdump",
    "wireshark",
    "iptables",
    "ufw",
    "shutdown",
    "reboot",
    "poweroff",
    "halt",
    "mkfs",
    "dd",
    "shred",
    "fdisk",
    "parted",
]

DEFAULT_EXCLUDE_PATHS = [
    "~/.ssh",
    "~/.gnupg",
    "~/.aws/credentials",
    "~/.config/gcloud",
    "/etc/shadow",
]


# --------------------------------------------------------------------------- #
# Coerción de listas
# --------------------------------------------------------------------------- #
def split_csv(value: Any) -> Any:
    """Convierte `"a,b"` o `"a"` en lista; deja pasar lo que ya es lista.

    `_coerce` (el que lee variables de entorno) solo convierte a lista las cadenas
    que CONTIENEN una coma, así que un valor único llegaba como `str` y pydantic
    reventaba: `JARVIS__ROUTER__DEFAULT_CHAIN=gemini` (un solo proveedor, algo
    perfectamente razonable) producía un ValidationError de diez líneas.
    """
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


class _ConfigBase(BaseModel):
    """Base de los configs con campos `list[str]`: los normaliza al entrar.

    Se hace en `mode="before"` para que dé igual de dónde venga el valor
    (TOML, variable de entorno, `Settings(...)` a mano): el campo siempre acaba
    siendo una lista de verdad.
    """

    @model_validator(mode="before")
    @classmethod
    def _split_list_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        for name, field in cls.model_fields.items():
            if name in out and isinstance(out[name], str) and get_origin(field.annotation) is list:
                out[name] = split_csv(out[name])
        return out


# --------------------------------------------------------------------------- #
# Modelos
# --------------------------------------------------------------------------- #
class IdentityConfig(_ConfigBase):
    name: str = "Jarvis"
    language: str = "es"
    tone: str = "formal"
    verbosity: str = "normal"
    wake_words: list[str] = Field(default_factory=lambda: ["jarvis"])


class RouterConfig(_ConfigBase):
    default_chain: list[str] = Field(
        default_factory=lambda: ["gemini", "nvidia", "anthropic", "openai", "ollama"]
    )
    profile: str = "general"
    max_steps_per_turn: int = 6
    timeout_s: float = 30.0
    max_retries: int = 2
    backoff_base_s: float = 0.8
    max_rpm: int = 12
    health_cache_s: int = 60
    circuit_breaker_failures: int = 3
    circuit_breaker_cooldown_s: int = 300
    model_cheap: str = "gemini-2.5-flash-lite"
    model_general: str = "gemini-3.7-flash"
    model_reasoner: str = "claude-sonnet-5"
    model_vision: str = "gemini-3.1-pro"
    model_offline: str = "qwen2.5:7b-instruct"
    #: Modelo a usar cuando el failover cambia de proveedor (ver `Router`).
    fallback_models: dict[str, str] = Field(
        default_factory=lambda: {
            "openai": "gpt-5.6-luna",
            "anthropic": "claude-haiku-4-5",
            "gemini": "gemini-3.7-flash",
            "nvidia": "deepseek-ai/deepseek-v3.2",
            "ollama": "qwen2.5:7b-instruct",
            "echo": "echo-local",
        }
    )
    local_matcher_enabled: bool = True
    local_matcher_min_confidence: float = 0.86
    semantic_cache_enabled: bool = False
    semantic_cache_ttl_s: int = 45

    @field_validator("max_steps_per_turn")
    @classmethod
    def _clamp_steps(cls, v: int) -> int:
        # Tope duro contra espirales de coste (ADR-0003).
        return max(1, min(v, 12))

    @field_validator("local_matcher_min_confidence")
    @classmethod
    def _clamp_conf(cls, v: float) -> float:
        return max(0.0, min(v, 1.0))


class BudgetConfig(BaseModel):
    usd_per_day: float = 0.50
    tokens_per_day: int = 2_000_000
    actions_per_hour: int = 120
    warn_at_pct: int = 80
    hard_stop: bool = True


class ProviderConfig(BaseModel):
    model_config = {"validate_assignment": True}

    enabled: bool = True
    base_url: str = ""
    api_key_env: str = ""
    anthropic_version: str = "2023-06-01"
    api_key: SecretStr | None = None

    def resolve_api_key(self) -> str | None:
        """La clave puede venir inyectada o del entorno (nunca se loggea)."""
        if self.api_key is not None:
            # Puede ser SecretStr (normal) o str si alguien asignó el campo desde
            # una fuente externa sin validación. Ambos casos se aceptan sin romper.
            value = (
                self.api_key.get_secret_value() if isinstance(self.api_key, SecretStr) else str(self.api_key)
            )
            return value or None
        if self.api_key_env:
            return os.environ.get(self.api_key_env) or None
        return None


class ProvidersConfig(BaseModel):
    openai: ProviderConfig = Field(default_factory=ProviderConfig)
    anthropic: ProviderConfig = Field(default_factory=ProviderConfig)
    gemini: ProviderConfig = Field(default_factory=ProviderConfig)
    nvidia: ProviderConfig = Field(default_factory=ProviderConfig)
    ollama: ProviderConfig = Field(default_factory=ProviderConfig)


class MemoryConfig(BaseModel):
    max_turns_in_context: int = 24
    max_context_tokens: int = 6000
    summarize_on_overflow: bool = True
    persist_sessions: bool = True


class PrivacyConfig(_ConfigBase):
    offline: bool = False
    redact_secrets: bool = True
    store_transcripts: bool = True
    exclude_paths: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDE_PATHS))


class PolicyConfig(_ConfigBase):
    auto_approve_max_tier: str = "T1"
    approval_timeout_s: int = 60
    require_typed_confirmation_for_t3: bool = True
    jail_roots: list[str] = Field(default_factory=lambda: list(DEFAULT_JAIL_ROOTS))
    shell_allowlist: list[str] = Field(default_factory=lambda: list(DEFAULT_SHELL_ALLOWLIST))
    shell_timeout_s: int = 20
    shell_max_output_bytes: int = 20_000
    restricted_binaries: list[str] = Field(default_factory=lambda: list(DEFAULT_RESTRICTED_BINARIES))


class WatchdogConfig(_ConfigBase):
    enabled: bool = True
    interval_s: int = 30
    disk_warn_pct: int = 85
    disk_crit_pct: int = 93
    ram_warn_pct: int = 85
    ram_crit_pct: int = 95
    swap_warn_pct: int = 60
    load_warn_factor: float = 1.5
    temp_warn_c: int = 78
    temp_crit_c: int = 90
    battery_low_pct: int = 20
    cooldown_s: int = 21_600
    quiet_hours: list[str] = Field(default_factory=list)
    speak_high_severity: bool = False


class VoiceConfig(BaseModel):
    enabled: bool = False
    stt_mode: str = "local"
    stt_model: str = "small"
    stt_language: str = "es"
    tts_engine: str = "piper"
    tts_voice: str = "es_ES-davefx-medium"
    wake_word_engine: str = "openwakeword"
    wake_word_threshold: float = 0.6
    sample_rate: int = 16_000
    vad_threshold: float = 0.5
    silence_ms: int = 700
    barge_in: bool = True


class ServerConfig(_ConfigBase):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    require_token: bool = True
    cors_origins: list[str] = Field(default_factory=list)


class UIConfig(BaseModel):
    theme: str = "dark"
    show_cost: bool = True
    show_tier_badges: bool = True
    spinner: str = "dots"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file_enabled: bool = True
    max_bytes: int = 5_242_880
    backups: int = 3


class Settings(BaseModel):
    """Configuración completa validada de JarvisM."""

    identity: IdentityConfig = Field(default_factory=IdentityConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    providers: ProvidersConfig = Field(default_factory=ProvidersConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    watchdog: WatchdogConfig = Field(default_factory=WatchdogConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Rutas resueltas en tiempo de ejecución (no se configuran en TOML).
    data_dir: Path = Field(default_factory=lambda: Path(user_data_dir(APP_NAME)))
    config_dir: Path = Field(default_factory=lambda: Path(user_config_dir(APP_NAME)))
    log_dir: Path = Field(default_factory=lambda: Path(user_log_dir(APP_NAME)))
    sources: list[str] = Field(default_factory=list)

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.config_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)
            # 700 en el directorio de datos: contiene auditoría y memoria.
            # En Windows chmod es casi un no-op y puede lanzar OSError.
            with contextlib.suppress(OSError):
                d.chmod(0o700)

    @property
    def audit_db(self) -> Path:
        return self.data_dir / "audit.sqlite3"

    @property
    def memory_db(self) -> Path:
        return self.data_dir / "memory.sqlite3"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "jarvis.log"

    def effective_offline(self) -> bool:
        """Offline explícito o implícito (ningún proveedor en la nube tiene clave)."""
        if self.privacy.offline:
            return True
        cloud = ("openai", "anthropic", "gemini", "nvidia")
        return not any(getattr(self.providers, p).resolve_api_key() for p in cloud)


# --------------------------------------------------------------------------- #
# Carga por capas
# --------------------------------------------------------------------------- #
def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _coerce(raw: str) -> Any:
    """Las variables de entorno son texto; las convertimos al tipo declarado."""
    low = raw.strip().lower()
    if low in {"true", "yes", "on"}:
        return True
    if low in {"false", "no", "off"}:
        return False
    if low in {"null", "none", ""}:
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    if "," in raw and not raw.startswith("["):
        # Listas simples vía coma: JARVIS__ROUTER__DEFAULT_CHAIN=gemini,openai
        return [item.strip() for item in raw.split(",") if item.strip()]
    return raw


def _apply_env(config: dict[str, Any]) -> list[str]:
    """Aplica JARVIS__SECCION__CLAVE y las claves planas de proveedor."""
    applied: list[str] = []
    prefix = "JARVIS__"
    for env_name, raw in os.environ.items():
        if not env_name.startswith(prefix) or raw == "":
            continue
        parts = [p.lower() for p in env_name[len(prefix) :].split("__") if p]
        if not parts:
            continue
        node = config
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):  # pragma: no cover - configuración inválida
                break
        else:
            node[parts[-1]] = _coerce(raw)
            applied.append(env_name)

    # Claves planas de proveedor -> providers.<name>.api_key
    for provider, env_name in {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "nvidia": "NVIDIA_API_KEY",
        "ollama": "OLLAMA_API_KEY",
    }.items():
        value = os.environ.get(env_name)
        if value:
            config.setdefault("providers", {}).setdefault(provider, {})["api_key"] = value
            applied.append(env_name)

    for provider in ("openai", "anthropic", "gemini", "nvidia", "ollama"):
        value = os.environ.get(f"{provider.upper()}_BASE_URL")
        if value:
            config.setdefault("providers", {}).setdefault(provider, {})["base_url"] = value
            applied.append(f"{provider.upper()}_BASE_URL")
    return applied


def _load_dotenv() -> None:
    """Carga .env del cwd o de la raíz del proyecto si existe."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv es dependencia core
        return
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            return


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Punto de acceso único. Usa `reload_settings()` en tests."""
    _load_dotenv()

    layers: list[tuple[str, dict[str, Any]]] = [("package-defaults", _read_toml(DEFAULT_CONFIG_PATH))]
    user_cfg = Path(user_config_dir(APP_NAME)) / "config.toml"
    layers.append((str(user_cfg), _read_toml(user_cfg)))
    local_cfg = Path.cwd() / "jarvis.toml"
    layers.append((str(local_cfg), _read_toml(local_cfg)))

    config: dict[str, Any] = {}
    sources: list[str] = []
    for name, data in layers:
        if data:
            config = _deep_merge(config, data)
            sources.append(name)

    env_applied = _apply_env(config)
    if env_applied:
        sources.append(f"env({len(env_applied)} vars)")

    settings = Settings(**config)
    settings.sources = sources
    settings.ensure_dirs()
    return settings


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()


def expand_path(value: str) -> Path:
    """Expande ~ y variables de entorno, y normaliza.

    Se usa `os.path` a propósito: `Path.expanduser()` no expande variables de
    entorno y aquí sí queremos soportar rutas como `$HOME/notas` en la config.
    """
    return Path(os.path.expanduser(os.path.expandvars(value))).resolve()  # noqa: PTH111
