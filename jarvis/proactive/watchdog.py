"""Watchdog proactivo: monitores + motor de sugerencias (Fase 4).

Diseño clave (docs/01 §4):
  - los monitores son funciones PURAS sobre datos del adapter → testeables sin SO;
  - una alerta pasa por deduplicador con cooldown antes de convertirse en sugerencia;
  - las sugerencias NUNCA ejecutan nada: proponen un `ToolCall` que el usuario aprueba;
  - horas silenciosas y modo presentación se respetan.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from jarvis.config.settings import Settings, WatchdogConfig
from jarvis.core.events import SUGGESTION_EMITTED, WATCHDOG_ALERT, get_bus
from jarvis.platforms.base import OSAdapter, Severity
from jarvis.safety.policy import RiskTier

log = logging.getLogger("jarvis.watchdog")


@dataclass(slots=True)
class SystemSnapshot:
    """Todo lo que un monitor necesita. Se captura una vez por pasada."""

    ts: float
    disks: list[dict[str, Any]] = field(default_factory=list)
    ram_used_pct: float = 0.0
    ram_total_mb: float = 0.0
    swap_used_pct: float = 0.0
    load: tuple[float, float, float] = (0.0, 0.0, 0.0)
    cpu_count: int = 1
    battery_pct: float | None = None
    battery_charging: bool = False
    temps: dict[str, float] = field(default_factory=dict)
    top_procs: list[dict[str, Any]] = field(default_factory=list)
    os_name: str = ""


@dataclass(slots=True)
class Alert:
    monitor: str
    severity: Severity
    title: str
    detail: str
    suggested_skill: str | None = None
    suggested_args: dict[str, Any] = field(default_factory=dict)
    suggested_tier: RiskTier = RiskTier.T0
    key: str = ""

    def __post_init__(self) -> None:
        if not self.key:
            self.key = f"{self.monitor}:{self.title}"

    def as_suggestion(self) -> str:
        action = ""
        if self.suggested_skill:
            args = ", ".join(f"{k}={v!r}" for k, v in self.suggested_args.items())
            action = f"\n   → Propuesta: {self.suggested_skill}({args}) [{self.suggested_tier.value}]"
        return f"[{self.severity.value.upper()}] {self.title}\n   {self.detail}{action}"


Monitor = Callable[[SystemSnapshot, WatchdogConfig], list[Alert]]


# --------------------------------------------------------------------------- #
# Monitores (funciones puras)
# --------------------------------------------------------------------------- #
def monitor_disk(snap: SystemSnapshot, cfg: WatchdogConfig) -> list[Alert]:
    alerts: list[Alert] = []
    for disk in snap.disks:
        pct = float(disk.get("used_pct", 0))
        mount = str(disk.get("mount", "?"))
        if pct >= cfg.disk_crit_pct:
            alerts.append(
                Alert(
                    monitor="disk.full",
                    severity=Severity.CRITICAL,
                    title=f"Disco {mount} al {pct:.0f}%",
                    detail=(
                        f"Quedan {disk.get('free_gb', '?')} GB libres. Por encima del "
                        f"{cfg.disk_crit_pct}% el sistema empieza a fallar (logs, caches, swap)."
                    ),
                    suggested_skill="system.processes",
                    suggested_tier=RiskTier.T0,
                )
            )
        elif pct >= cfg.disk_warn_pct:
            alerts.append(
                Alert(
                    monitor="disk.warn",
                    severity=Severity.WARNING,
                    title=f"Disco {mount} al {pct:.0f}%",
                    detail=f"{disk.get('free_gb', '?')} GB libres. Aún hay margen, pero conviene limpiar.",
                    suggested_skill="system.disk",
                    suggested_tier=RiskTier.T0,
                )
            )
    return alerts


def monitor_memory(snap: SystemSnapshot, cfg: WatchdogConfig) -> list[Alert]:
    if snap.ram_used_pct >= cfg.ram_crit_pct:
        top = ", ".join(f"{p.get('name')} ({p.get('mem_mb')} MB)" for p in snap.top_procs[:3])
        return [
            Alert(
                monitor="ram.critical",
                severity=Severity.CRITICAL,
                title=f"RAM al {snap.ram_used_pct:.0f}%",
                detail=(
                    f"Consumo crítico{f': {top}' if top else ''}. "
                    "Riesgo de que el OOM killer cierre aplicaciones."
                ),
                suggested_skill="system.processes",
                suggested_args={"sort_by": "mem", "top_n": 8},
                suggested_tier=RiskTier.T0,
            )
        ]
    if snap.ram_used_pct >= cfg.ram_warn_pct:
        return [
            Alert(
                monitor="ram.warn",
                severity=Severity.WARNING,
                title=f"RAM al {snap.ram_used_pct:.0f}%",
                detail="Consumo alto sostenido. Puede estar notándose en la fluidez del escritorio.",
                suggested_skill="system.processes",
                suggested_args={"sort_by": "mem", "top_n": 8},
                suggested_tier=RiskTier.T0,
            )
        ]
    if snap.swap_used_pct >= cfg.swap_warn_pct and snap.swap_used_pct > 0:
        return [
            Alert(
                monitor="swap.high",
                severity=Severity.WARNING,
                title=f"Swap al {snap.swap_used_pct:.0f}%",
                detail="El sistema está paginando: la RAM física no da para la carga actual.",
                suggested_skill="system.info",
                suggested_tier=RiskTier.T0,
            )
        ]
    return []


def monitor_load(snap: SystemSnapshot, cfg: WatchdogConfig) -> list[Alert]:
    threshold = cfg.load_warn_factor * max(1, snap.cpu_count)
    if snap.load[0] >= threshold:
        return [
            Alert(
                monitor="load.high",
                severity=Severity.WARNING,
                title=f"Carga {snap.load[0]:.2f} con {snap.cpu_count} CPUs",
                detail=(
                    f"La carga media supera {cfg.load_warn_factor} veces el número de núcleos "
                    f"(umbral {threshold:.1f}). Algo está saturando la CPU."
                ),
                suggested_skill="system.processes",
                suggested_args={"sort_by": "cpu", "top_n": 8},
                suggested_tier=RiskTier.T0,
            )
        ]
    return []


def monitor_battery(snap: SystemSnapshot, cfg: WatchdogConfig) -> list[Alert]:
    if snap.battery_pct is None or snap.battery_charging:
        return []
    if snap.battery_pct <= cfg.battery_low_pct:
        top = ", ".join(f"{p.get('name')}" for p in snap.top_procs[:2])
        return [
            Alert(
                monitor="battery.low",
                severity=Severity.CRITICAL
                if snap.battery_pct <= cfg.battery_low_pct / 2
                else Severity.WARNING,
                title=f"Batería al {snap.battery_pct:.0f}%",
                detail=f"Conecta el cargador{f'. Consumo alto ahora mismo: {top}' if top else ''}.",
                suggested_skill="system.battery",
                suggested_tier=RiskTier.T0,
            )
        ]
    return []


def monitor_temperature(snap: SystemSnapshot, cfg: WatchdogConfig) -> list[Alert]:
    hot = {k: v for k, v in snap.temps.items() if v >= cfg.temp_warn_c}
    if not hot:
        return []
    worst = max(hot.items(), key=lambda kv: kv[1])
    critical = worst[1] >= cfg.temp_crit_c
    return [
        Alert(
            monitor="temp.high",
            severity=Severity.CRITICAL if critical else Severity.WARNING,
            title=f"{worst[0]} a {worst[1]:.0f} °C",
            detail=(
                f"Umbral crítico {cfg.temp_crit_c} °C alcanzado: reduce la carga ya."
                if critical
                else f"Supera el umbral de aviso ({cfg.temp_warn_c} °C). Revisa ventilación y cargas."
            ),
            suggested_skill="system.processes",
            suggested_args={"sort_by": "cpu", "top_n": 5},
            suggested_tier=RiskTier.T0,
        )
    ]


DEFAULT_MONITORS: tuple[Monitor, ...] = (
    monitor_disk,
    monitor_memory,
    monitor_load,
    monitor_battery,
    monitor_temperature,
)


# --------------------------------------------------------------------------- #
# Deduplicador y horas silenciosas
# --------------------------------------------------------------------------- #
class CooldownTracker:
    """Evita el spam: la misma alerta no se repite hasta pasado el cooldown."""

    def __init__(self, cooldown_s: int) -> None:
        self.cooldown_s = cooldown_s
        self._seen: dict[str, float] = {}
        self.suppressed = 0

    def should_emit(self, key: str, *, now: float | None = None) -> bool:
        current = now if now is not None else time.time()
        last = self._seen.get(key)
        if last is not None and (current - last) < self.cooldown_s:
            self.suppressed += 1
            return False
        self._seen[key] = current
        return True

    def reset(self) -> None:
        self._seen.clear()
        self.suppressed = 0


def in_quiet_hours(quiet_hours: list[str], *, now: float | None = None) -> bool:
    """`quiet_hours` son rangos 'HH:MM-HH:MM' (pueden cruzar la medianoche)."""
    if not quiet_hours:
        return False
    current = time.localtime(now if now is not None else time.time())
    minutes = current.tm_hour * 60 + current.tm_min
    for spec in quiet_hours:
        try:
            start_s, end_s = spec.split("-", 1)
            start = _to_minutes(start_s)
            end = _to_minutes(end_s)
        except ValueError:
            log.warning("quiet_hours con formato inválido: %r (se espera HH:MM-HH:MM)", spec)
            continue
        if start <= end:
            if start <= minutes < end:
                return True
        elif minutes >= start or minutes < end:  # cruza la medianoche
            return True
    return False


def _to_minutes(text: str) -> int:
    hours, minutes = text.strip().split(":", 1)
    return int(hours) * 60 + int(minutes)


# --------------------------------------------------------------------------- #
# Watchdog
# --------------------------------------------------------------------------- #
class Watchdog:
    def __init__(
        self,
        settings: Settings,
        adapter: OSAdapter,
        *,
        monitors: tuple[Monitor, ...] = DEFAULT_MONITORS,
        on_suggestion: Callable[[Alert], None] | None = None,
    ) -> None:
        self.settings = settings
        self.cfg = settings.watchdog
        self.adapter = adapter
        self.monitors = monitors
        self.cooldown = CooldownTracker(self.cfg.cooldown_s)
        self.on_suggestion = on_suggestion
        self.bus = get_bus()
        self.history: list[dict[str, Any]] = []
        self.passes = 0
        self._stop = False

    # -- captura ---------------------------------------------------------- #
    def capture(self) -> SystemSnapshot:
        info = self.adapter.system_info()
        snap = SystemSnapshot(
            ts=time.time(),
            disks=[
                {"mount": d.mount, "used_pct": d.used_pct, "free_gb": d.free_gb, "total_gb": d.total_gb}
                for d in self.adapter.disks()
            ],
            load=info.load_avg,
            cpu_count=info.cpu_count,
            temps=self.adapter.temperatures(),
            os_name=info.os_name,
        )
        if info.memory:
            snap.ram_used_pct = info.memory.used_pct
            snap.ram_total_mb = info.memory.total_mb
            snap.swap_used_pct = info.memory.swap_used_pct
        battery = self.adapter.battery()
        if battery and battery.present:
            snap.battery_pct = battery.percent
            snap.battery_charging = battery.charging
        snap.top_procs = [
            {"name": p.name, "mem_mb": p.mem_mb, "cpu_pct": p.cpu_pct}
            for p in self.adapter.processes(top_n=5, sort_by="mem")
        ]
        return snap

    # -- pasada ----------------------------------------------------------- #
    def evaluate(self, snapshot: SystemSnapshot | None = None) -> list[Alert]:
        """Una pasada: captura, monitores, cooldown. Devuelve las alertas EMITIDAS."""
        self.passes += 1
        snap = snapshot or self.capture()
        if in_quiet_hours(self.cfg.quiet_hours, now=snap.ts):
            log.debug("hora silenciosa: se omiten las sugerencias")
            return []
        emitted: list[Alert] = []
        for monitor in self.monitors:
            try:
                alerts = monitor(snap, self.cfg)
            except Exception as exc:
                log.warning("monitor %s falló: %s", getattr(monitor, "__name__", monitor), exc)
                continue
            for alert in alerts:
                self.bus.publish(
                    WATCHDOG_ALERT,
                    source="watchdog",
                    monitor=alert.monitor,
                    severity=alert.severity.value,
                    title=alert.title,
                )
                if not self.cooldown.should_emit(alert.key, now=snap.ts):
                    continue
                emitted.append(alert)
                self.history.append(
                    {
                        "ts": snap.ts,
                        "monitor": alert.monitor,
                        "severity": alert.severity.value,
                        "title": alert.title,
                        "detail": alert.detail,
                    }
                )
                self.bus.publish(
                    SUGGESTION_EMITTED,
                    source="watchdog",
                    id=alert.key,
                    kind=alert.monitor,
                    severity=alert.severity.value,
                )
                if self.on_suggestion is not None:
                    self.on_suggestion(alert)
                else:
                    self._deliver(alert)
        return emitted

    def _deliver(self, alert: Alert) -> None:
        """Entrega por defecto: notificación del SO + log. La voz llega en Fase 3."""
        self.adapter.notify(f"Jarvis · {alert.title}", alert.detail, level=alert.severity)
        log.info("sugerencia: %s", alert.as_suggestion())

    # -- bucle ------------------------------------------------------------ #
    def run(self, *, once: bool = False, interval_s: int | None = None) -> list[Alert]:
        self._stop = False
        if once:
            return self.evaluate()
        period = interval_s or self.cfg.interval_s
        collected: list[Alert] = []
        try:
            while not self._stop:
                collected.extend(self.evaluate())
                time.sleep(max(5, period))
        except KeyboardInterrupt:
            self.stop()
        return collected

    def stop(self) -> None:
        self._stop = True

    def summary(self) -> dict[str, Any]:
        return {
            "passes": self.passes,
            "emitted": len(self.history),
            "suppressed_by_cooldown": self.cooldown.suppressed,
            "interval_s": self.cfg.interval_s,
            "quiet_hours": self.cfg.quiet_hours,
            "last": self.history[-10:],
        }
