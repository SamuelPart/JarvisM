"""`OSAdapter`: la única frontera entre JarvisM y el sistema operativo (ADR-0004).

Regla del proyecto: `subprocess` no aparece fuera de este paquete ni de
`skills/shell.py`. Lo comprueba `tests/test_no_raw_subprocess.py`.
"""

from __future__ import annotations

import enum
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class Platform(str, enum.Enum):
    LINUX = "linux"
    WINDOWS = "windows"
    MACOS = "macos"
    UNKNOWN = "unknown"


class Severity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(slots=True)
class Capability:
    """Estado de una capacidad del sistema (herramienta externa presente o no)."""

    name: str
    available: bool
    backend: str = ""
    hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "available": self.available, "backend": self.backend, "hint": self.hint}


@dataclass(slots=True)
class Volume:
    mount: str
    device: str
    total_gb: float
    used_gb: float
    free_gb: float
    used_pct: float
    fstype: str = ""


@dataclass(slots=True)
class Proc:
    pid: int
    name: str
    user: str = ""
    cpu_pct: float = 0.0
    mem_mb: float = 0.0
    cmdline: str = ""


@dataclass(slots=True)
class MemoryInfo:
    total_mb: float
    available_mb: float
    used_pct: float
    swap_total_mb: float = 0.0
    swap_used_pct: float = 0.0


@dataclass(slots=True)
class Battery:
    present: bool
    percent: float = 0.0
    charging: bool = False
    seconds_remaining: int | None = None


@dataclass(slots=True)
class WindowInfo:
    id: str = ""
    title: str = ""
    app: str = ""
    workspace: int | None = None


@dataclass(slots=True)
class AppInfo:
    name: str
    executable: str = ""
    source: str = ""
    categories: list[str] = field(default_factory=list)


@dataclass(slots=True)
class LaunchResult:
    ok: bool
    app: str
    detail: str = ""
    pid: int | None = None


@dataclass(slots=True)
class SystemInfo:
    platform: Platform
    os_name: str
    os_version: str
    hostname: str
    user: str
    kernel: str
    cpu_count: int
    cpu_model: str = ""
    load_avg: tuple[float, float, float] = (0.0, 0.0, 0.0)
    uptime_s: float = 0.0
    memory: MemoryInfo | None = None
    desktop: str = ""
    display_server: str = ""
    is_root: bool = False
    python: str = ""


@dataclass(slots=True)
class UpdateSummary:
    package_manager: str = ""
    total: int = 0
    security: int = 0
    detail: str = ""
    packages: list[str] = field(default_factory=list)


class OSAdapter(ABC):
    """Interfaz común. Las capacidades ausentes devuelven `Capability(False, hint=...)`."""

    platform: Platform = Platform.UNKNOWN

    # -- detección -------------------------------------------------------- #
    @abstractmethod
    def capabilities(self) -> list[Capability]:
        """Matriz honesta de qué puede hacer JarvisM en esta máquina."""

    def supports(self, capability: str) -> bool:
        return any(c.name == capability and c.available for c in self.capabilities())

    # -- sistema ---------------------------------------------------------- #
    @abstractmethod
    def system_info(self) -> SystemInfo: ...

    @abstractmethod
    def disks(self) -> list[Volume]: ...

    @abstractmethod
    def processes(self, top_n: int = 10, sort_by: str = "mem") -> list[Proc]: ...

    def battery(self) -> Battery | None:
        return None

    def temperatures(self) -> dict[str, float]:
        return {}

    def network_listeners(self) -> list[dict[str, Any]]:
        return []

    # -- apps y ventanas -------------------------------------------------- #
    @abstractmethod
    def list_apps(self) -> list[AppInfo]: ...

    @abstractmethod
    def launch(self, app: str, args: list[str] | None = None) -> LaunchResult: ...

    def windows(self) -> list[WindowInfo]:
        return []

    def active_window(self) -> WindowInfo | None:
        return None

    def focus_window(self, title_pattern: str) -> bool:
        return False

    def close_window(self, title_pattern: str) -> bool:
        return False

    # -- escritorio ------------------------------------------------------- #
    def set_volume(self, percent: int) -> bool:
        return False

    def get_volume(self) -> int | None:
        return None

    def mute(self, value: bool) -> bool:
        return False

    def set_brightness(self, percent: int) -> bool:
        return False

    def notify(self, title: str, body: str, *, level: Severity = Severity.INFO) -> bool:
        return False

    @abstractmethod
    def clipboard_get(self) -> str: ...

    @abstractmethod
    def clipboard_set(self, text: str) -> bool: ...

    # -- paquetes --------------------------------------------------------- #
    def pending_updates(self) -> UpdateSummary:
        return UpdateSummary(detail="no soportado en esta plataforma")

    # -- utilidades ------------------------------------------------------- #
    @staticmethod
    def which(binary: str) -> str | None:
        return shutil.which(binary)

    @staticmethod
    def first_available(*binaries: str) -> str | None:
        for binary in binaries:
            if found := shutil.which(binary):
                return found
        return None

    @staticmethod
    def home() -> Path:
        return Path.home()
