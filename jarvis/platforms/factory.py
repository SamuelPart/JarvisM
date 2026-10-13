"""Fábrica de adapters y utilidades transversales de plataforma."""

from __future__ import annotations

import sys
from functools import lru_cache

from jarvis.platforms.base import OSAdapter, Platform


def detect_platform() -> Platform:
    if sys.platform.startswith("linux"):
        return Platform.LINUX
    if sys.platform == "darwin":
        return Platform.MACOS
    if sys.platform in {"win32", "cygwin"}:
        return Platform.WINDOWS
    return Platform.UNKNOWN


class _UnsupportedAdapter(OSAdapter):
    """Fallback para plataformas no soportadas: nunca explota, siempre explica."""

    platform = Platform.UNKNOWN

    def capabilities(self):
        from jarvis.platforms.base import Capability

        return [Capability("platform", False, sys.platform, "plataforma no soportada por JarvisM")]

    def system_info(self):
        import getpass
        import os
        import platform as _p

        from jarvis.platforms.base import SystemInfo

        return SystemInfo(
            platform=Platform.UNKNOWN,
            os_name=_p.system(),
            os_version=_p.release(),
            hostname=_p.node(),
            user=getpass.getuser(),
            kernel=_p.version(),
            cpu_count=os.cpu_count() or 1,
            python=_p.python_version(),
        )

    def disks(self):
        import shutil

        from jarvis.platforms.base import Volume

        usage = shutil.disk_usage("/")
        return [
            Volume(
                mount="/",
                device="?",
                total_gb=round(usage.total / 1024**3, 2),
                used_gb=round(usage.used / 1024**3, 2),
                free_gb=round(usage.free / 1024**3, 2),
                used_pct=round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
            )
        ]

    def processes(self, top_n: int = 10, sort_by: str = "mem"):
        return []

    def list_apps(self):
        return []

    def launch(self, app, args=None):
        from jarvis.platforms.base import LaunchResult

        return LaunchResult(False, app, "plataforma no soportada")

    def clipboard_get(self):
        return ""

    def clipboard_set(self, text):
        return False


@lru_cache(maxsize=1)
def get_adapter() -> OSAdapter:
    """Devuelve el adapter del sistema actual (import perezoso: no carga los otros)."""
    current = detect_platform()
    if current is Platform.LINUX:
        from jarvis.platforms.linux import LinuxAdapter

        return LinuxAdapter()
    if current is Platform.MACOS:
        from jarvis.platforms.macos import MacOSAdapter

        return MacOSAdapter()
    if current is Platform.WINDOWS:
        from jarvis.platforms.windows import WindowsAdapter

        return WindowsAdapter()
    return _UnsupportedAdapter()


def reset_adapter_cache() -> None:
    """Para tests que inyectan un adapter falso."""
    get_adapter.cache_clear()
