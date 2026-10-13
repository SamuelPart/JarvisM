"""`MacOSAdapter`.

Estrategia: `osascript` (AppleScript/JXA) para el escritorio, `sysctl`/`df`/`ps`
para el sistema, `open -a` y `mdfind` (Spotlight) para apps y archivos, y
`pbcopy`/`pbpaste` para el portapapeles.

En macOS moderno casi todo lo que toca ventanas, notificaciones o micrófono exige
permisos explícitos del usuario en *Ajustes → Privacidad y seguridad*. `jarvis doctor`
los reporta como capacidades no disponibles con la ruta exacta para concederlos.
"""

from __future__ import annotations

import getpass
import os
import platform
import re
import shutil
from pathlib import Path
from typing import Any

from jarvis.platforms._proc import run_command, spawn_detached
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


def _osa(script: str, *, timeout: float = 15.0) -> tuple[bool, str]:
    result = run_command(["osascript", "-e", script], timeout=timeout)
    if not result.ok:
        return False, (result.stderr or result.stdout).strip()
    return True, result.stdout.strip()


def _sysctl(key: str) -> str:
    result = run_command(["sysctl", "-n", key], timeout=5)
    return result.stdout.strip() if result.ok else ""


class MacOSAdapter(OSAdapter):
    platform = Platform.MACOS

    # ------------------------------------------------------------------ #
    def capabilities(self) -> list[Capability]:
        caps: list[Capability] = []
        caps.append(
            Capability(
                "osascript", shutil.which("osascript") is not None, "osascript", "osascript no encontrado"
            )
        )
        caps.append(Capability("apps", shutil.which("open") is not None, "open -a"))
        caps.append(
            Capability("spotlight", shutil.which("mdfind") is not None, "mdfind", "Spotlight desactivado")
        )
        caps.append(Capability("clipboard", shutil.which("pbcopy") is not None, "pbcopy/pbpaste"))
        caps.append(
            Capability(
                "windows",
                True,
                "System Events",
                "requiere permiso de Accesibilidad para la terminal que lance Jarvis",
            )
        )
        caps.append(Capability("notify", True, "display notification"))
        caps.append(Capability("volume", True, "osascript 'set volume output volume'"))
        caps.append(
            Capability(
                "brightness",
                shutil.which("brightness") is not None,
                "brightness",
                "brew install brightness (AppleScript no lo expone de forma fiable)",
            )
        )
        caps.append(Capability("media", shutil.which("playerctl") is not None or True, "osascript/Music.app"))
        caps.append(Capability("packages", shutil.which("brew") is not None, "brew", "brew no instalado"))
        caps.append(
            Capability(
                "not_root", os.geteuid() != 0, f"uid={os.geteuid()}", "JarvisM no debe ejecutarse como root"
            )
        )
        return caps

    # ------------------------------------------------------------------ #
    def system_info(self) -> SystemInfo:
        page_size = int(_sysctl("hw.pagesize") or 4096)
        mem_bytes = int(_sysctl("hw.memsize") or 0) / 1024**2
        vm = run_command(["vm_stat"], timeout=5).stdout
        free_pages = 0
        for line in vm.splitlines():
            m = re.match(r"(Pages free|Pages inactive):\s+(\d+)\.", line)
            if m:
                free_pages += int(m.group(2))
        available_mb = round(free_pages * page_size / 1024**2, 1)
        memory = MemoryInfo(
            total_mb=round(mem_bytes, 1),
            available_mb=available_mb,
            used_pct=round((mem_bytes - available_mb) / mem_bytes * 100, 1) if mem_bytes else 0.0,
        )
        uptime_s = 0.0
        boot = run_command(["sysctl", "-n", "kern.boottime"], timeout=5).stdout
        m = re.search(r"sec = (\d+)", boot)
        if m:
            import time as _time

            uptime_s = max(0.0, _time.time() - int(m.group(1)))
        load_raw = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
        return SystemInfo(
            platform=Platform.MACOS,
            os_name="macOS",
            os_version=platform.mac_ver()[0] or platform.release(),
            hostname=platform.node(),
            user=getpass.getuser(),
            kernel=_sysctl("kern.osrelease") or platform.release(),
            cpu_count=os.cpu_count() or 1,
            cpu_model=_sysctl("machdep.cpu.brand_string")
            or ("Apple Silicon" if platform.machine() == "arm64" else ""),
            load_avg=load_raw,
            uptime_s=uptime_s,
            memory=memory,
            desktop="Aqua",
            display_server="WindowServer",
            is_root=os.geteuid() == 0,
            python=platform.python_version(),
        )

    def disks(self) -> list[Volume]:
        out: list[Volume] = []
        result = run_command(["df", "-k"], timeout=10)
        if not result.ok:
            return out
        for line in result.stdout.splitlines()[1:]:
            fields = line.split()
            if len(fields) < 9 or not fields[0].startswith("/dev/"):
                continue
            mount = " ".join(fields[8:])
            if mount.startswith(("/System/Volumes/", "/private/var")):
                continue
            total_kb, used_kb, free_kb = int(fields[1]), int(fields[2]), int(fields[3])
            if total_kb <= 0:
                continue
            out.append(
                Volume(
                    mount=mount,
                    device=fields[0],
                    total_gb=round(total_kb / 1024**2, 2),
                    used_gb=round(used_kb / 1024**2, 2),
                    free_gb=round(free_kb / 1024**2, 2),
                    used_pct=round(used_kb / total_kb * 100, 1),
                    fstype="apfs",
                )
            )
        return sorted(out, key=lambda v: v.used_pct, reverse=True)

    def processes(self, top_n: int = 10, sort_by: str = "mem") -> list[Proc]:
        flag = "-r" if sort_by == "cpu" else "-m"
        result = run_command(["ps", "-axo", "pid,pcpu,rss,user,comm", flag], timeout=10)
        if not result.ok:
            return []
        procs: list[Proc] = []
        for line in result.stdout.splitlines()[1 : top_n + 1]:
            fields = line.split(None, 4)
            if len(fields) < 5:
                continue
            try:
                procs.append(
                    Proc(
                        pid=int(fields[0]),
                        name=Path(fields[4]).name,
                        user=fields[3],
                        cpu_pct=float(fields[1]),
                        mem_mb=round(int(fields[2]) / 1024, 1),
                        cmdline=fields[4],
                    )
                )
            except ValueError:
                continue
        return procs

    def battery(self) -> Battery | None:
        result = run_command(["pmset", "-g", "batt"], timeout=8)
        if not result.ok:
            return None
        out = result.stdout
        m = re.search(r"(\d+)%", out)
        if not m:
            return None
        charging = "AC Power" in out or "charging" in out.lower()
        remaining = None
        time_m = re.search(r"(\d+):(\d+) remaining", out)
        if time_m:
            remaining = int(time_m.group(1)) * 3600 + int(time_m.group(2)) * 60
        return Battery(
            present=True, percent=float(m.group(1)), charging=charging, seconds_remaining=remaining
        )

    def temperatures(self) -> dict[str, float]:
        # Requiere `osx-cpu-temp` o `istats`; sin ellos, macOS no expone sensores
        # a usuarios no root. Lo reportamos vacío en vez de fallar.
        if tool := shutil.which("osx-cpu-temp"):
            result = run_command([tool], timeout=5)
            m = re.search(r"([\d.]+)", result.stdout)
            if result.ok and m:
                return {"cpu": float(m.group(1))}
        return {}

    def network_listeners(self) -> list[dict[str, Any]]:
        result = run_command(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], timeout=15)
        if not result.ok:
            return []
        rows: list[dict[str, Any]] = []
        for line in result.stdout.splitlines()[1:51]:
            fields = line.split()
            if len(fields) >= 9:
                rows.append({"proto": "tcp", "local": fields[8], "process": f"{fields[0]}({fields[1]})"})
        return rows

    # ------------------------------------------------------------------ #
    def list_apps(self) -> list[AppInfo]:
        apps: list[AppInfo] = []
        for root in ("/Applications", str(Path.home() / "Applications"), "/System/Applications"):
            directory = Path(root)
            if not directory.is_dir():
                continue
            for bundle in sorted(directory.glob("*.app")):
                apps.append(
                    AppInfo(name=bundle.stem, executable=str(bundle / "Contents/MacOS"), source=str(bundle))
                )
            for bundle in sorted(directory.glob("*/*.app")):
                apps.append(
                    AppInfo(name=bundle.stem, executable=str(bundle / "Contents/MacOS"), source=str(bundle))
                )
        return apps

    def launch(self, app: str, args: list[str] | None = None) -> LaunchResult:
        query = app.strip()
        if not query:
            return LaunchResult(False, app, "nombre de aplicación vacío")
        if shutil.which(query):
            pid, error = spawn_detached([query, *(args or [])])
            if pid:
                return LaunchResult(True, query, f"lanzado desde PATH: {query}", pid=pid)
            return LaunchResult(False, query, error)
        cmd = ["open", "-a", query]
        if args:
            cmd += ["--args", *args]
        result = run_command(cmd, timeout=20)
        if result.ok:
            return LaunchResult(True, query, f"lanzado con open -a {query}")
        # Spotlight como red de seguridad para nombres parciales.
        mdfind = run_command(
            ["mdfind", f"kMDItemKind == 'Application' && kMDItemDisplayName == '*{query}*'c"], timeout=15
        )
        if mdfind.ok:
            for line in mdfind.stdout.splitlines():
                if line.endswith(".app"):
                    retry = run_command(["open", line], timeout=20)
                    if retry.ok:
                        return LaunchResult(True, Path(line).stem, f"lanzado vía Spotlight: {line}")
        return LaunchResult(False, query, f"no encuentro la aplicación '{query}': {result.stderr[:150]}")

    def windows(self) -> list[WindowInfo]:
        script = (
            'tell application "System Events" to get name of every process whose background only is false'
        )
        ok, out = _osa(script)
        if not ok:
            return []
        return [WindowInfo(title=name.strip(), app=name.strip()) for name in out.split(", ") if name.strip()]

    def active_window(self) -> WindowInfo | None:
        ok, out = _osa(
            'tell application "System Events" to get name of first application process whose frontmost is true'  # noqa: E501
        )
        if not ok or not out:
            return None
        app = out.strip()
        ok2, title = _osa(
            f'tell application "System Events" to tell process "{app}" to get name of front window'
        )
        return WindowInfo(title=title.strip() if ok2 else "", app=app)

    def focus_window(self, title_pattern: str) -> bool:
        script = (
            f'tell application "System Events" to set frontmost of (first process whose name contains '
            f'"{title_pattern}") to true'
        )
        ok, _ = _osa(script)
        return ok

    def close_window(self, title_pattern: str) -> bool:
        script = (
            'tell application "System Events" to click button 2 of window 1 of (first process whose '
            f'name contains "{title_pattern}")'
        )
        ok, _ = _osa(script)
        return ok

    # ------------------------------------------------------------------ #
    def set_volume(self, percent: int) -> bool:
        percent = max(0, min(100, percent))
        ok, _ = _osa(f"set volume output volume {percent}")
        return ok

    def get_volume(self) -> int | None:
        ok, out = _osa("output volume of (get volume settings)")
        try:
            return int(out) if ok else None
        except ValueError:
            return None

    def mute(self, value: bool) -> bool:
        ok, _ = _osa(f"set volume {'with' if value else 'without'} output muted")
        return ok

    def set_brightness(self, percent: int) -> bool:
        percent = max(0, min(100, percent))
        if tool := shutil.which("brightness"):
            return run_command([tool, f"{percent / 100:.2f}"], timeout=8).ok
        return False

    def notify(self, title: str, body: str, *, level: Severity = Severity.INFO) -> bool:
        safe_title = title.replace('"', "'")[:120]
        safe_body = body.replace('"', "'")[:400]
        ok, _ = _osa(f'display notification "{safe_body}" with title "{safe_title}"')
        return ok

    def clipboard_get(self) -> str:
        result = run_command(["pbpaste"], timeout=5)
        return result.stdout if result.ok else ""

    def clipboard_set(self, text: str) -> bool:
        return run_command(["pbcopy"], timeout=5, stdin_text=text).ok

    # ------------------------------------------------------------------ #
    def pending_updates(self) -> UpdateSummary:
        if brew := shutil.which("brew"):
            result = run_command([brew, "outdated", "--formula"], timeout=120)
            packages = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
            return UpdateSummary(
                package_manager="brew",
                total=len(packages),
                packages=packages[:30],
                detail=f"{len(packages)} fórmulas desactualizadas en Homebrew"
                if packages
                else "Homebrew al día",
            )
        result = run_command(["softwareupdate", "--list"], timeout=120)
        if result.ok:
            items = re.findall(r"^\*\s+Label:\s*(.+)$", result.stdout + result.stderr, re.MULTILINE)
            security = sum(1 for i in items if "security" in i.lower())
            return UpdateSummary(
                package_manager="softwareupdate",
                total=len(items),
                security=security,
                packages=items[:30],
                detail=f"{len(items)} actualizaciones de macOS pendientes" if items else "macOS al día",
            )
        return UpdateSummary(detail="no se pudo consultar softwareupdate")
