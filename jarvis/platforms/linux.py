"""`LinuxAdapter`.

Lee directamente de `/proc` y `/sys` para las métricas (cero dependencias) y
usa las utilidades estándar del escritorio cuando existen (`wmctrl`, `pactl`,
`brightnessctl`, `notify-send`, `wl-paste`/`xclip`, `gio`, `apt`). Cada una se
detecta en caliente y su ausencia se reporta como capacidad no disponible.
"""

from __future__ import annotations

import getpass
import os
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

TIMEOUT = 8


def _run(cmd: list[str], *, timeout: float = TIMEOUT, cwd: str | None = None) -> tuple[int, str, str]:
    """Ejecuta sin shell (nunca `shell=True`). Delegado en `platforms._proc`."""
    result = run_command(cmd, timeout=timeout, cwd=cwd)
    return result.code, result.stdout, result.stderr


def _read(path: str | Path) -> str:
    try:
        return Path(path).read_text(errors="replace").strip()
    except OSError:
        return ""


def _detect_display_server() -> str:
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session:
        return session
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "desconocido"


def _os_pretty() -> tuple[str, str]:
    data = _read("/etc/os-release")
    name, version = "Linux", ""
    for line in data.splitlines():
        if line.startswith("PRETTY_NAME="):
            name = line.split("=", 1)[1].strip('"')
        elif line.startswith("VERSION_ID="):
            version = line.split("=", 1)[1].strip('"')
    return name, version


class LinuxAdapter(OSAdapter):
    platform = Platform.LINUX

    # ------------------------------------------------------------------ #
    def capabilities(self) -> list[Capability]:
        caps: list[Capability] = []

        def add(name: str, binaries: tuple[str, ...], hint: str) -> None:
            found = self.first_available(*binaries)
            caps.append(
                Capability(
                    name=name,
                    available=found is not None,
                    backend=Path(found).name if found else "",
                    hint="" if found else hint,
                )
            )

        add("windows", ("wmctrl", "xdotool"), "sudo apt install wmctrl xdotool")
        add("notify", ("notify-send",), "sudo apt install libnotify-bin")
        add(
            "clipboard", ("wl-copy", "xclip", "xsel"), "sudo apt install xclip (X11) o wl-clipboard (Wayland)"
        )
        add("volume", ("wpctl", "pactl", "amixer"), "instalados con PipeWire/PulseAudio")
        add("brightness", ("brightnessctl", "xbacklight"), "sudo apt install brightnessctl")
        add("media", ("playerctl",), "sudo apt install playerctl")
        add("launch_desktop", ("gio", "gtk-launch"), "parte de glib2 / GTK")
        add("sensors", ("sensors",), "sudo apt install lm-sensors && sudo sensors-detect")
        add("packages", ("apt", "dnf", "pacman", "zypper"), "gestor de paquetes del distro")
        add("services", ("systemctl",), "systemd no disponible")

        display = _detect_display_server()
        caps.append(
            Capability(
                name="display_server",
                available=display in {"x11", "wayland"},
                backend=display,
                hint="sin servidor gráfico (sesión SSH/TTY): las capacidades de escritorio no funcionarán",
            )
        )
        caps.append(
            Capability(
                name="audio_capture",
                available=bool(_read("/proc/asound/cards")) or self.which("arecord") is not None,
                backend="alsa/pipewire",
                hint="no se detectan dispositivos de audio (arecord -l)",
            )
        )
        caps.append(
            Capability(
                name="not_root",
                available=os.geteuid() != 0 if hasattr(os, "geteuid") else True,
                backend=f"uid={os.geteuid() if hasattr(os, 'geteuid') else -1}",
                hint="JarvisM no debe ejecutarse como root (docs/03 §1)",
            )
        )
        return caps

    # ------------------------------------------------------------------ #
    def system_info(self) -> SystemInfo:
        os_name, os_version = _os_pretty()
        try:
            load = os.getloadavg()
        except OSError:
            load = (0.0, 0.0, 0.0)

        uptime = 0.0
        raw = _read("/proc/uptime")
        if raw:
            try:
                uptime = float(raw.split()[0])
            except (ValueError, IndexError):
                uptime = 0.0

        cpu_model = ""
        for line in _read("/proc/cpuinfo").splitlines():
            if line.lower().startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break

        return SystemInfo(
            platform=Platform.LINUX,
            os_name=os_name,
            os_version=os_version,
            hostname=os.uname().nodename,
            user=getpass.getuser(),
            kernel=os.uname().release,
            cpu_count=os.cpu_count() or 1,
            cpu_model=cpu_model,
            load_avg=load,
            uptime_s=uptime,
            memory=self._memory(),
            desktop=os.environ.get("XDG_CURRENT_DESKTOP", ""),
            display_server=_detect_display_server(),
            is_root=hasattr(os, "geteuid") and os.geteuid() == 0,
            python=__import__("sys").version.split()[0],
        )

    def _memory(self) -> MemoryInfo:
        info: dict[str, int] = {}
        for line in _read("/proc/meminfo").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                info[parts[0].rstrip(":")] = int(parts[1])  # kB
        total = info.get("MemTotal", 0) / 1024
        available = info.get("MemAvailable", info.get("MemFree", 0)) / 1024
        swap_total = info.get("SwapTotal", 0) / 1024
        swap_free = info.get("SwapFree", 0) / 1024
        used_pct = ((total - available) / total * 100) if total else 0.0
        swap_pct = ((swap_total - swap_free) / swap_total * 100) if swap_total else 0.0
        return MemoryInfo(
            total_mb=round(total, 1),
            available_mb=round(available, 1),
            used_pct=round(used_pct, 1),
            swap_total_mb=round(swap_total, 1),
            swap_used_pct=round(swap_pct, 1),
        )

    def disks(self) -> list[Volume]:
        out: list[Volume] = []
        seen: set[str] = set()
        for line in _read("/proc/mounts").splitlines():
            parts = line.split()
            if len(parts) < 3:
                continue
            device, mount, fstype = parts[0], parts[1], parts[2]
            if not device.startswith("/") and fstype not in {"zfs", "btrfs"}:
                continue
            if mount in seen or mount.startswith(("/snap", "/boot/efi")):
                continue
            try:
                usage = shutil.disk_usage(mount)
            except OSError:
                continue
            seen.add(mount)
            out.append(
                Volume(
                    mount=mount,
                    device=device,
                    total_gb=round(usage.total / 1024**3, 2),
                    used_gb=round(usage.used / 1024**3, 2),
                    free_gb=round(usage.free / 1024**3, 2),
                    used_pct=round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
                    fstype=fstype,
                )
            )
        return sorted(out, key=lambda v: v.used_pct, reverse=True)

    def processes(self, top_n: int = 10, sort_by: str = "mem") -> list[Proc]:
        procs: list[Proc] = []
        hertz = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
        uptime_raw = _read("/proc/uptime")
        try:
            uptime = float(uptime_raw.split()[0])
        except (ValueError, IndexError, AttributeError):
            uptime = 0.0
        for entry in Path("/proc").iterdir() if Path("/proc").is_dir() else []:
            if not entry.name.isdigit():
                continue
            stat = _read(entry / "stat")
            if not stat:
                continue
            try:
                name = stat[stat.index("(") + 1 : stat.rindex(")")]
                fields = stat[stat.rindex(")") + 2 :].split()
                utime, stime = int(fields[11]), int(fields[12])
                starttime = int(fields[19])
                rss_pages = int(fields[21])
            except (ValueError, IndexError):
                continue
            cpu_pct = 0.0
            if uptime > 0 and hertz > 0:
                seconds = uptime - (starttime / hertz)
                if seconds > 0:
                    cpu_pct = round(((utime + stime) / hertz) / seconds * 100, 1)
            mem_mb = round(rss_pages * 4096 / 1024**2, 1)
            user = ""
            status = _read(entry / "status")
            m = re.search(r"^Uid:\s+(\d+)", status, re.MULTILINE)
            if m:
                try:
                    import pwd

                    user = pwd.getpwuid(int(m.group(1))).pw_name
                except (KeyError, ImportError, ValueError):
                    user = m.group(1)
            cmdline = _read(entry / "cmdline").replace("\x00", " ").strip()
            procs.append(
                Proc(
                    pid=int(entry.name),
                    name=name,
                    user=user,
                    cpu_pct=cpu_pct,
                    mem_mb=mem_mb,
                    cmdline=cmdline[:400],
                )
            )

        key = (lambda p: p.cpu_pct) if sort_by == "cpu" else (lambda p: p.mem_mb)
        return sorted(procs, key=key, reverse=True)[:top_n]

    def battery(self) -> Battery | None:
        base = Path("/sys/class/power_supply")
        if not base.is_dir():
            return None
        for entry in sorted(base.iterdir()):
            if entry.name.startswith("BAT"):
                try:
                    now = int(_read(entry / "energy_now") or _read(entry / "charge_now") or 0)
                    full = int(_read(entry / "energy_full") or _read(entry / "charge_full") or 0)
                    power = int(_read(entry / "power_now") or _read(entry / "current_now") or 0)
                except ValueError:
                    continue
                percent = round(now / full * 100, 1) if full else 0.0
                status = _read(entry / "status").lower()
                remaining = None
                if power and status == "discharging":
                    remaining = int(now / power * 3600)
                return Battery(
                    present=True,
                    percent=percent,
                    charging=status in {"charging", "full"},
                    seconds_remaining=remaining,
                )
        return None

    def temperatures(self) -> dict[str, float]:
        temps: dict[str, float] = {}
        base = Path("/sys/class/thermal")
        if base.is_dir():
            for zone in sorted(base.glob("thermal_zone*")):
                label = _read(zone / "type") or zone.name
                raw = _read(zone / "temp")
                try:
                    temps[f"{label}"] = round(int(raw) / 1000, 1)
                except ValueError:
                    continue
        if not temps and self.which("sensors"):
            code, out, _ = _run(["sensors"])
            if code == 0:
                for match in re.finditer(r"^([^\n:]+):\s*\+?([\d.]+)°C", out, re.MULTILINE):
                    temps[match.group(1).strip()] = float(match.group(2))
        return temps

    def network_listeners(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        binary = self.first_available("ss", "netstat")
        if not binary:
            return rows
        args = [binary, "-tulnp"]
        code, out, _ = _run(args)
        if code != 0:
            return rows
        for line in out.splitlines()[1:]:
            fields = line.split()
            if len(fields) < 5:
                continue
            rows.append(
                {
                    "proto": fields[0],
                    "local": fields[3],
                    "process": fields[-1],
                }
            )
        return rows[:50]

    # ------------------------------------------------------------------ #
    def list_apps(self) -> list[AppInfo]:
        apps: dict[str, AppInfo] = {}
        for directory in (
            "/usr/share/applications",
            "/var/lib/flatpak/exports/share/applications",
            str(Path.home() / ".local/share/applications"),
        ):
            root = Path(directory)
            if not root.is_dir():
                continue
            for desktop in root.glob("*.desktop"):
                try:
                    content = desktop.read_text(errors="replace")
                except OSError:
                    continue
                if "NoDisplay=true" in content or "Hidden=true" in content:
                    continue
                name = _desktop_field(content, "Name")
                if not name:
                    continue
                executable = _desktop_field(content, "Exec") or ""
                categories = _desktop_field(content, "Categories") or ""
                apps[name.lower()] = AppInfo(
                    name=name,
                    executable=executable,
                    source=str(desktop),
                    categories=[c for c in categories.split(";") if c],
                )
        return sorted(apps.values(), key=lambda a: a.name.lower())

    def launch(self, app: str, args: list[str] | None = None) -> LaunchResult:
        query = app.strip().lower()
        if not query:
            return LaunchResult(False, app, "nombre de aplicación vacío")

        # 1) entrada .desktop (lo más fiable en Linux de escritorio)
        candidate = self._find_desktop(query)
        if candidate:
            launcher = self.first_available("gio", "gtk-launch")
            if launcher and launcher.endswith("gio"):
                code, _, _err = _run([launcher, "launch", candidate.stem])
                if code == 0:
                    return LaunchResult(True, candidate.stem, "lanzado con gio launch")
            elif launcher:
                code, _, _err = _run([launcher, candidate.stem])
                if code == 0:
                    return LaunchResult(True, candidate.stem, "lanzado con gtk-launch")
            exec_line = _desktop_field(candidate.read_text(errors="replace"), "Exec") or ""
            command = re.sub(r"%[a-zA-Z]", "", exec_line).split()
            if command:
                return self._spawn(command + (args or []), app)

        # 2) binario en el PATH
        binary = shutil.which(query) or shutil.which(query.split()[0])
        if binary:
            return self._spawn([binary, *(args or [])], app)

        # 3) coincidencia difusa sobre el catálogo de .desktop
        fuzzy = [a for a in self.list_apps() if query in a.name.lower()]
        if fuzzy:
            return self.launch(fuzzy[0].name, args)

        return LaunchResult(False, app, f"no encuentro '{app}' ni como aplicación ni en el PATH")

    def _find_desktop(self, query: str) -> Path | None:
        for directory in ("/usr/share/applications", str(Path.home() / ".local/share/applications")):
            root = Path(directory)
            if not root.is_dir():
                continue
            direct = root / f"{query}.desktop"
            if direct.is_file():
                return direct
            for desktop in root.glob("*.desktop"):
                if query in desktop.stem.lower():
                    return desktop
        return None

    def _spawn(self, cmd: list[str], app: str) -> LaunchResult:
        pid, error = spawn_detached(cmd)
        if pid is None:
            return LaunchResult(False, app, f"no se pudo lanzar: {error}")
        return LaunchResult(True, app, f"lanzado: {' '.join(cmd[:3])}", pid=pid)

    def windows(self) -> list[WindowInfo]:
        wmctrl = self.which("wmctrl")
        if wmctrl:
            code, out, _ = _run([wmctrl, "-l"])
            if code == 0:
                result = []
                for line in out.splitlines():
                    fields = line.split(None, 3)
                    if len(fields) >= 4:
                        host_title = fields[3]
                        title = host_title.split(" ", 1)[1] if " " in host_title else host_title
                        result.append(WindowInfo(id=fields[0], title=title.strip(), app=""))
                return result
        xdotool = self.which("xdotool")
        if xdotool:
            code, out, _ = _run([xdotool, "search", "--onlyvisible", "--name", ""])
            if code == 0:
                ids = out.split()[:50]
                result = []
                for wid in ids:
                    code2, name, _ = _run([xdotool, "getwindowname", wid])
                    if code2 == 0 and name.strip():
                        result.append(WindowInfo(id=wid, title=name.strip()))
                return result
        return []

    def active_window(self) -> WindowInfo | None:
        xdotool = self.which("xdotool")
        if xdotool:
            code, wid, _ = _run([xdotool, "getactivewindow"])
            if code == 0 and wid.strip():
                code2, name, _ = _run([xdotool, "getwindowname", wid.strip()])
                if code2 == 0:
                    return WindowInfo(id=wid.strip(), title=name.strip())
        wmctrl = self.which("wmctrl")
        if wmctrl:
            code, out, _run_all = _run([wmctrl, "-l"])
            if code == 0 and out:
                last = out.splitlines()[-1]
                return WindowInfo(title=last)
        return None

    def focus_window(self, title_pattern: str) -> bool:
        tool = self.first_available("wmctrl", "xdotool")
        if not tool:
            return False
        if tool.endswith("wmctrl"):
            code, _, _ = _run([tool, "-a", title_pattern])
            return code == 0
        code, wid, _ = _run([tool, "search", "--name", title_pattern])
        if code == 0 and wid.strip():
            first = wid.split()[0]
            code2, _, _ = _run([tool, "windowactivate", first])
            return code2 == 0
        return False

    def close_window(self, title_pattern: str) -> bool:
        tool = self.first_available("wmctrl", "xdotool")
        if not tool:
            return False
        if tool.endswith("wmctrl"):
            code, _, _ = _run([tool, "-c", title_pattern])
            return code == 0
        code, wid, _ = _run([tool, "search", "--name", title_pattern])
        if code == 0 and wid.strip():
            code2, _, _ = _run([tool, "windowclose", wid.split()[0]])
            return code2 == 0
        return False

    # ------------------------------------------------------------------ #
    def set_volume(self, percent: int) -> bool:
        percent = max(0, min(150, percent))
        if self.which("wpctl"):
            code, _, _ = _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent}%"])
            return code == 0
        if self.which("pactl"):
            code, _, _ = _run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"])
            return code == 0
        if self.which("amixer"):
            code, _, _ = _run(["amixer", "-q", "sset", "Master", f"{percent}%"])
            return code == 0
        return False

    def get_volume(self) -> int | None:
        if self.which("wpctl"):
            code, out, _ = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
            if code == 0:
                m = re.search(r"([\d.]+)", out)
                if m:
                    return int(float(m.group(1)) * 100)
        if self.which("pactl"):
            code, out, _ = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
            if code == 0:
                m = re.search(r"(\d+)%", out)
                if m:
                    return int(m.group(1))
        if self.which("amixer"):
            code, out, _ = _run(["amixer", "sget", "Master"])
            if code == 0:
                m = re.search(r"\[(\d+)%\]", out)
                if m:
                    return int(m.group(1))
        return None

    def mute(self, value: bool) -> bool:
        state = "1" if value else "0"
        for cmd in (
            ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", state],
            ["pactl", "set-sink-mute", "@DEFAULT_SINK@", state],
            ["amixer", "-q", "sset", "Master", "mute" if value else "unmute"],
        ):
            if self.which(cmd[0]):
                code, _, _ = _run(cmd)
                return code == 0
        return False

    def set_brightness(self, percent: int) -> bool:
        percent = max(0, min(100, percent))
        if self.which("brightnessctl"):
            code, _, _ = _run(["brightnessctl", "set", f"{percent}%"])
            return code == 0
        if self.which("xbacklight"):
            code, _, _ = _run(["xbacklight", "-set", str(percent)])
            return code == 0
        return False

    def notify(self, title: str, body: str, *, level: Severity = Severity.INFO) -> bool:
        if not self.which("notify-send"):
            return False
        urgency = {"info": "normal", "warning": "normal", "critical": "critical"}[level.value]
        code, _, _ = _run(["notify-send", "-u", urgency, title, body])
        return code == 0

    def clipboard_get(self) -> str:
        if os.environ.get("WAYLAND_DISPLAY") and self.which("wl-paste"):
            code, out, _ = _run(["wl-paste", "--no-newline"])
            if code == 0:
                return out
        if self.which("xclip"):
            code, out, _ = _run(["xclip", "-selection", "clipboard", "-o"])
            if code == 0:
                return out
        if self.which("xsel"):
            code, out, _ = _run(["xsel", "--clipboard", "--output"])
            if code == 0:
                return out
        return ""

    def clipboard_set(self, text: str) -> bool:
        if os.environ.get("WAYLAND_DISPLAY") and self.which("wl-copy"):
            return _run(["wl-copy", text])[0] == 0
        if self.which("xclip"):
            return _pipe_to(text, ["xclip", "-selection", "clipboard"])
        if self.which("xsel"):
            return _pipe_to(text, ["xsel", "--clipboard", "--input"])
        return False

    # ------------------------------------------------------------------ #
    def pending_updates(self) -> UpdateSummary:
        if self.which("apt-get"):
            # `-s` simula: no instala nada, solo lista. Requiere índices actualizados
            # (`sudo apt update`), que es una acción T3 propuesta por separado.
            code, out, err = _run(["apt-get", "-s", "upgrade"], timeout=90)
            if code != 0:
                return UpdateSummary(package_manager="apt", detail=f"apt-get -s falló: {err.strip()[:200]}")
            packages = re.findall(r"^Inst\s+(\S+)", out, re.MULTILINE)
            security = sum(1 for line in out.splitlines() if line.startswith("Inst") and "-security" in line)
            return UpdateSummary(
                package_manager="apt",
                total=len(packages),
                security=security,
                packages=packages[:30],
                detail=(
                    f"{len(packages)} paquetes actualizables ({security} de seguridad) según los índices "
                    "actuales. Ejecuta `sudo apt update` para refrescarlos."
                    if packages
                    else "sin actualizaciones pendientes según los índices actuales"
                ),
            )
        for manager in ("dnf", "pacman", "zypper"):
            if self.which(manager):
                return UpdateSummary(
                    package_manager=manager, detail=f"soporte de {manager} previsto en Fase 4"
                )
        return UpdateSummary(detail="no se detectó gestor de paquetes")


def _desktop_field(content: str, key: str) -> str:
    """Lee un campo de la sección [Desktop Entry] respetando el locale."""
    for line in content.splitlines():
        if line.startswith(f"{key}[") or line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def _pipe_to(text: str, cmd: list[str]) -> bool:
    """Envía texto por stdin a un comando (xclip/xsel/wl-copy)."""
    return run_command(cmd, timeout=5, stdin_text=text).ok
