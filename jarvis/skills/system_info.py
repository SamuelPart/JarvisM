"""Skills de lectura del sistema. Todos T0: inocuos, sin red, sin escritura."""

from __future__ import annotations

import time
from dataclasses import asdict
from datetime import datetime
from typing import Any

from jarvis.safety.policy import RiskTier
from jarvis.skills.base import Skill, SkillResult


class SystemInfoSkill(Skill):
    name = "system.info"
    description = (
        "Devuelve un resumen del sistema operativo: distribución, kernel, host, usuario, CPUs, "
        "carga, memoria RAM y swap, uptime y entorno de escritorio. Úsalo para preguntas como "
        "'cómo está el equipo', 'cuánta RAM queda', 'qué sistema es este'."
    )
    parameters = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    tier = RiskTier.T0

    def execute(self) -> SkillResult:
        info = self.adapter.system_info()
        data = asdict(info)
        mem = info.memory
        lines = [
            f"{info.os_name} {info.os_version} · kernel {info.kernel}",
            f"Host {info.hostname} · usuario {info.user}"
            + (f" · escritorio {info.desktop} ({info.display_server})" if info.desktop else ""),
            f"CPU: {info.cpu_count} núcleos{_suffix(info.cpu_model)} · carga {fmt_load(info.load_avg)}",
        ]
        if mem:
            lines.append(
                f"RAM: {mem.used_pct}% usada "
                f"({round(mem.total_mb / 1024, 1)} GB totales, "
                f"{round(mem.available_mb / 1024, 1)} GB disponibles)"
            )
            if mem.swap_total_mb > 0:
                lines.append(f"Swap: {mem.swap_used_pct}% de {round(mem.swap_total_mb / 1024, 1)} GB")
        lines.append(f"Uptime: {fmt_uptime(info.uptime_s)}")
        if info.is_root:
            lines.append("⚠ Ejecutándose como root: no recomendado (docs/03 §1).")
        return SkillResult.success("\n".join(lines), data=data)


def fmt_load(load: tuple[float, float, float]) -> str:
    return f"{load[0]:.2f} / {load[1]:.2f} / {load[2]:.2f}"


def fmt_uptime(seconds: float) -> str:
    seconds = int(seconds)
    days, rem = divmod(seconds, 86_400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days} d")
    if hours:
        parts.append(f"{hours} h")
    parts.append(f"{minutes} min")
    return " ".join(parts)


def _suffix(cpu_model: str) -> str:
    return f" ({cpu_model})" if cpu_model else ""


class DiskUsageSkill(Skill):
    name = "system.disk"
    description = (
        "Lista los volúmenes montados con su capacidad total, usada, libre y porcentaje de uso, "
        "ordenados por ocupación. Úsalo para 'cuánto disco me queda', 'el disco está lleno', "
        "'espacio libre'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "mount": {
                "type": "string",
                "description": "Opcional: filtrar por punto de montaje (p. ej. '/' o 'C:\\').",
            }
        },
        "additionalProperties": False,
    }
    tier = RiskTier.T0

    def execute(self, mount: str | None = None) -> SkillResult:
        volumes = self.adapter.disks()
        if mount:
            volumes = [v for v in volumes if v.mount.rstrip("/\\") == mount.rstrip("/\\")]
            if not volumes:
                return SkillResult.failure(f"no encuentro el volumen {mount}")
        if not volumes:
            return SkillResult.failure("no se pudo leer ningún volumen")
        lines = [
            f"{v.mount}: {v.used_pct}% usado ({v.free_gb} GB libres de {v.total_gb} GB, {v.fstype})"
            for v in volumes
        ]
        worst = volumes[0]
        if worst.used_pct >= self.settings.watchdog.disk_crit_pct:
            lines.append(f"⚠ {worst.mount} está al {worst.used_pct}%: riesgo crítico de espacio.")
        return SkillResult.success("\n".join(lines), data=[asdict(v) for v in volumes])


class ProcessesSkill(Skill):
    name = "system.processes"
    description = (
        "Lista los procesos que más recursos consumen, con PID, nombre, usuario, CPU y memoria. "
        "Úsalo para 'qué está consumiendo', 'qué procesos hay', 'por qué va lento el equipo'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "top_n": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "default": 8,
                "description": "Cuántos procesos mostrar.",
            },
            "sort_by": {
                "type": "string",
                "enum": ["mem", "cpu"],
                "default": "mem",
                "description": "Ordenar por memoria o por CPU.",
            },
        },
        "additionalProperties": False,
    }
    tier = RiskTier.T0

    def execute(self, top_n: int = 8, sort_by: str = "mem") -> SkillResult:
        procs = self.adapter.processes(top_n=top_n, sort_by=sort_by)
        if not procs:
            return SkillResult.failure("no se pudieron leer los procesos")
        unit = "MEM" if sort_by == "mem" else "CPU"
        lines = [f"Top {len(procs)} procesos por {unit.lower()}:"]
        for p in procs:
            value = f"{p.mem_mb} MB" if sort_by == "mem" else f"{p.cpu_pct}%"
            lines.append(f"  {p.pid:>7}  {value:>10}  {p.name[:40]} ({p.user or '?'})")
        return SkillResult.success("\n".join(lines), data=[asdict(p) for p in procs])


class BatterySkill(Skill):
    name = "system.battery"
    description = "Estado de la batería: porcentaje, si está cargando y tiempo restante estimado."
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    tier = RiskTier.T0

    def execute(self) -> SkillResult:
        battery = self.adapter.battery()
        if battery is None or not battery.present:
            return SkillResult.success(
                "Este equipo no tiene batería (o no es legible): está conectado a la red."
            )
        state = "cargando" if battery.charging else "en descarga"
        text = f"Batería al {battery.percent:.0f}%, {state}"
        if battery.seconds_remaining and not battery.charging:
            hours = battery.seconds_remaining // 3600
            minutes = (battery.seconds_remaining % 3600) // 60
            text += f" · quedan ~{hours} h {minutes} min"
        return SkillResult.success(text, data=asdict(battery))


class TemperatureSkill(Skill):
    name = "system.temperature"
    description = "Temperaturas de CPU y otras zonas térmicas disponibles en el sistema."
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    tier = RiskTier.T0

    def execute(self) -> SkillResult:
        temps = self.adapter.temperatures()
        if not temps:
            hint = ""
            cap = next((c for c in self.adapter.capabilities() if c.name == "sensors"), None)
            if cap and cap.hint:
                hint = f" Sugerencia: {cap.hint}."
            return SkillResult.success(f"No hay sensores de temperatura disponibles.{hint}")
        warn = self.settings.watchdog.temp_warn_c
        lines = [f"{k}: {v} °C" + (" ⚠" if v >= warn else "") for k, v in sorted(temps.items())]
        return SkillResult.success("Temperaturas → " + ", ".join(lines), data=temps)


class ListenersSkill(Skill):
    name = "system.listeners"
    description = (
        "Lista los puertos TCP/UDP en escucha y el proceso que los posee. Úsalo para "
        "'qué puertos tengo abiertos', revisión rápida de superficie expuesta."
    )
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    tier = RiskTier.T0

    def execute(self) -> SkillResult:
        rows = self.adapter.network_listeners()
        if not rows:
            return SkillResult.success("No hay puertos en escucha (o no se pudieron leer).")
        lines = [f"  {r.get('proto', '?')}  {r.get('local', '?'):<28} {r.get('process', '?')}" for r in rows]
        return SkillResult.success(f"{len(rows)} sockets en escucha:\n" + "\n".join(lines[:30]), data=rows)


class UpdateCheckSkill(Skill):
    name = "system.updates_check"
    description = (
        "Consulta (solo lectura, sin instalar nada) cuántas actualizaciones de paquetes hay "
        "pendientes y cuántas son de seguridad. Úsalo para 'tengo actualizaciones pendientes'."
    )
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    tier = RiskTier.T0

    def execute(self) -> SkillResult:
        started = time.perf_counter()
        summary = self.adapter.pending_updates()
        data = asdict(summary)
        data["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        if summary.total:
            text = f"{summary.total} actualizaciones pendientes"
            if summary.security:
                text += f", {summary.security} de seguridad"
            return SkillResult.success(text + ". " + summary.detail, data=data)
        return SkillResult.success(summary.detail or "Sin actualizaciones pendientes.", data=data)


class TimeSkill(Skill):
    name = "time.now"
    description = "Fecha, hora y zona horaria local actuales. Úsalo para 'qué hora es', 'qué día es'."
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    tier = RiskTier.T0

    def execute(self) -> SkillResult:
        now = datetime.now().astimezone()
        return SkillResult.success(
            now.strftime("Son las %H:%M del %A, %d de %B de %Y (%Z)."),
            data={"iso": now.isoformat(), "epoch": int(now.timestamp())},
        )


class CapabilitiesSkill(Skill):
    name = "system.capabilities"
    description = (
        "Informa de qué capacidades tiene JarvisM en esta máquina y qué falta instalar para "
        "habilitar las que no están. Úsalo para 'qué puedes hacer aquí', 'por qué no funciona X'."
    )
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    tier = RiskTier.T0

    def execute(self) -> SkillResult:
        caps = self.adapter.capabilities()
        data: list[dict[str, Any]] = [c.to_dict() for c in caps]
        ok = [c.name for c in caps if c.available]
        missing = [f"{c.name} → {c.hint}" for c in caps if not c.available and c.hint]
        text = f"Capacidades disponibles ({len(ok)}/{len(caps)}): " + ", ".join(ok)
        if missing:
            text += "\nFaltan:\n  " + "\n  ".join(missing)
        return SkillResult.success(text, data=data)
