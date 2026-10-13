"""Tests del watchdog: monitores puros, cooldown, horas silenciosas y entrega."""

from __future__ import annotations

import time

from jarvis.platforms.base import Severity
from jarvis.proactive.watchdog import (
    DEFAULT_MONITORS,
    Alert,
    CooldownTracker,
    SystemSnapshot,
    Watchdog,
    in_quiet_hours,
    monitor_battery,
    monitor_disk,
    monitor_load,
    monitor_memory,
    monitor_temperature,
)


def _snapshot(**kwargs) -> SystemSnapshot:
    base = {
        "ts": time.time(),
        "disks": [{"mount": "/", "used_pct": 40.0, "free_gb": 60.0, "total_gb": 100.0}],
        "ram_used_pct": 30.0,
        "ram_total_mb": 16384.0,
        "swap_used_pct": 0.0,
        "load": (0.4, 0.3, 0.2),
        "cpu_count": 4,
        "battery_pct": None,
        "battery_charging": False,
        "temps": {},
        "top_procs": [{"name": "firefox", "mem_mb": 900, "cpu_pct": 20}],
    }
    base.update(kwargs)
    return SystemSnapshot(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Monitores
# --------------------------------------------------------------------------- #
def test_disk_monitor_quiet_when_healthy(settings) -> None:
    assert monitor_disk(_snapshot(), settings.watchdog) == []


def test_disk_monitor_warns_and_crits(settings) -> None:
    warn = monitor_disk(
        _snapshot(disks=[{"mount": "/", "used_pct": 88.0, "free_gb": 12, "total_gb": 100}]), settings.watchdog
    )
    assert warn and warn[0].severity is Severity.WARNING

    crit = monitor_disk(
        _snapshot(disks=[{"mount": "/", "used_pct": 96.0, "free_gb": 4, "total_gb": 100}]), settings.watchdog
    )
    assert crit and crit[0].severity is Severity.CRITICAL


def test_memory_monitor_levels(settings) -> None:
    assert monitor_memory(_snapshot(ram_used_pct=50), settings.watchdog) == []
    assert monitor_memory(_snapshot(ram_used_pct=88), settings.watchdog)[0].severity is Severity.WARNING
    assert monitor_memory(_snapshot(ram_used_pct=97), settings.watchdog)[0].severity is Severity.CRITICAL


def test_swap_monitor_triggers_when_swapping(settings) -> None:
    alerts = monitor_memory(_snapshot(swap_used_pct=80), settings.watchdog)
    assert alerts and alerts[0].monitor == "swap.high"


def test_load_monitor_scales_with_cpu_count(settings) -> None:
    assert monitor_load(_snapshot(load=(3.0, 1, 1), cpu_count=4), settings.watchdog) == []
    assert monitor_load(_snapshot(load=(9.0, 5, 3), cpu_count=4), settings.watchdog)


def test_battery_monitor_ignores_charging(settings) -> None:
    assert monitor_battery(_snapshot(battery_pct=10, battery_charging=True), settings.watchdog) == []
    alerts = monitor_battery(_snapshot(battery_pct=10, battery_charging=False), settings.watchdog)
    assert alerts and alerts[0].monitor == "battery.low"


def test_temperature_monitor_levels(settings) -> None:
    assert monitor_temperature(_snapshot(temps={"cpu": 50.0}), settings.watchdog) == []
    warm = monitor_temperature(_snapshot(temps={"cpu": 80.0}), settings.watchdog)
    assert warm[0].severity is Severity.WARNING
    hot = monitor_temperature(_snapshot(temps={"cpu": 95.0}), settings.watchdog)
    assert hot[0].severity is Severity.CRITICAL


def test_every_monitor_suggests_a_concrete_skill(settings) -> None:
    """Una sugerencia sin acción propuesta no es accionable: es ruido."""
    snapshots = [
        _snapshot(disks=[{"mount": "/", "used_pct": 96, "free_gb": 1, "total_gb": 100}]),
        _snapshot(ram_used_pct=97),
        _snapshot(load=(20.0, 10, 5)),
        _snapshot(battery_pct=5, battery_charging=False),
        _snapshot(temps={"cpu": 95.0}),
    ]
    for snapshot in snapshots:
        alerts = [a for monitor in DEFAULT_MONITORS for a in monitor(snapshot, settings.watchdog)]
        assert alerts
        for alert in alerts:
            assert alert.suggested_skill, f"{alert.monitor} no propone ninguna acción"


# --------------------------------------------------------------------------- #
# Cooldown
# --------------------------------------------------------------------------- #
def test_cooldown_suppresses_repeats() -> None:
    tracker = CooldownTracker(cooldown_s=3600)
    now = time.time()
    assert tracker.should_emit("disk.full", now=now)
    assert not tracker.should_emit("disk.full", now=now + 10)
    assert not tracker.should_emit("disk.full", now=now + 3599)
    assert tracker.should_emit("disk.full", now=now + 3601)
    assert tracker.suppressed == 2


def test_cooldown_is_per_key() -> None:
    tracker = CooldownTracker(cooldown_s=3600)
    assert tracker.should_emit("disk.full")
    assert tracker.should_emit("ram.warn")


# --------------------------------------------------------------------------- #
# Horas silenciosas
# --------------------------------------------------------------------------- #
def test_quiet_hours_within_range() -> None:
    ts = time.mktime((2026, 10, 12, 23, 59, 0, 0, 0, -1))
    assert in_quiet_hours(["23:30-07:30"], now=ts)
    ts = time.mktime((2026, 10, 12, 3, 0, 0, 0, 0, -1))
    assert in_quiet_hours(["23:30-07:30"], now=ts)
    ts = time.mktime((2026, 10, 12, 12, 0, 0, 0, 0, -1))
    assert not in_quiet_hours(["23:30-07:30"], now=ts)


def test_quiet_hours_simple_range() -> None:
    ts = time.mktime((2026, 10, 12, 14, 0, 0, 0, 0, -1))
    assert in_quiet_hours(["13:00-15:00"], now=ts)
    assert not in_quiet_hours([], now=ts)


def test_bad_quiet_hours_format_is_ignored() -> None:
    assert not in_quiet_hours(["formato-malo"])


# --------------------------------------------------------------------------- #
# Watchdog completo
# --------------------------------------------------------------------------- #
def test_watchdog_emits_and_notifies(settings, fake_adapter) -> None:
    fake_adapter.disk_used_pct = 96.0
    watchdog = Watchdog(settings, fake_adapter)
    alerts = watchdog.evaluate()
    assert alerts
    assert fake_adapter.notifications, "debería haber notificado al usuario"
    assert watchdog.summary()["emitted"] == len(alerts)


def test_watchdog_suppresses_repeated_alerts(settings, fake_adapter) -> None:
    fake_adapter.disk_used_pct = 96.0
    watchdog = Watchdog(settings, fake_adapter)
    first = watchdog.evaluate()
    second = watchdog.evaluate()
    assert first
    assert second == []
    assert watchdog.summary()["suppressed_by_cooldown"] > 0


def test_watchdog_respects_quiet_hours(settings, fake_adapter) -> None:
    settings.watchdog.quiet_hours = ["00:00-23:59"]
    fake_adapter.disk_used_pct = 96.0
    watchdog = Watchdog(settings, fake_adapter)
    assert watchdog.evaluate() == []


def test_suggestion_is_actionable_and_mentions_tier() -> None:
    alert = Alert(
        monitor="disk.full",
        severity=Severity.CRITICAL,
        title="Disco / al 96%",
        detail="4 GB libres",
        suggested_skill="system.disk",
        suggested_args={},
    )
    text = alert.as_suggestion()
    assert "CRITICAL" in text
    assert "system.disk" in text
    assert "[T0]" in text


def test_watchdog_survives_a_broken_monitor(settings, fake_adapter) -> None:
    def evil_monitor(snap, cfg):
        raise RuntimeError("monitor roto")

    watchdog = Watchdog(settings, fake_adapter, monitors=(evil_monitor, *DEFAULT_MONITORS))
    fake_adapter.disk_used_pct = 96.0
    alerts = watchdog.evaluate()  # no debe propagar la excepción
    assert alerts
