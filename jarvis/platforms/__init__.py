"""Abstracción de sistema operativo (ADR-0004)."""

from jarvis.platforms.base import (
    AppInfo,
    Battery,
    Capability,
    LaunchResult,
    MemoryInfo,
    OSAdapter,
    Platform,
    Proc,
    Severity,
    SystemInfo,
    UpdateSummary,
    Volume,
    WindowInfo,
)
from jarvis.platforms.factory import detect_platform, get_adapter, reset_adapter_cache

__all__ = [
    "AppInfo",
    "Battery",
    "Capability",
    "LaunchResult",
    "MemoryInfo",
    "OSAdapter",
    "Platform",
    "Proc",
    "Severity",
    "SystemInfo",
    "UpdateSummary",
    "Volume",
    "WindowInfo",
    "detect_platform",
    "get_adapter",
    "reset_adapter_cache",
]
