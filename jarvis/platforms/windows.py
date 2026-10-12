"""`WindowsAdapter`.

Estrategia: PowerShell (`pwsh` si existe, si no `powershell.exe`) para todo lo
que en Linux sale de /proc, y Win32 vía `pywin32` cuando esté instalado (extra
opcional). Nada de `shell=True`: los comandos se pasan como lista de argumentos.

Probado contra Windows 10 21H2+ y Windows 11. En Windows Server sin escritorio
las capacidades gráficas se reportan como no disponibles en lugar de fallar.
"""

from __future__ import annotations

import getpass
import json
import os
import platform
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

PS_TIMEOUT = 25.0


def _ps(script: str, *, timeout: float = PS_TIMEOUT) -> tuple[bool, str]:
    """Ejecuta un script de PowerShell y devuelve (ok, stdout)."""
    exe = shutil.which("pwsh") or shutil.which("powershell")
    if not exe:
        return False, "PowerShell no disponible"
    result = run_command(
        [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
        timeout=timeout,
    )
    if not result.ok:
        return False, (result.stderr or result.stdout).strip()
    return True, result.stdout.strip()


def _ps_json(script: str, *, timeout: float = PS_TIMEOUT) -> Any:
    ok, out = _ps(f"{script} | ConvertTo-Json -Depth 4 -Compress", timeout=timeout)
    if not ok or not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


class WindowsAdapter(OSAdapter):
    platform = Platform.WINDOWS

    # ------------------------------------------------------------------ #
    def capabilities(self) -> list[Capability]:
        caps: list[Capability] = []
        ps = shutil.which("pwsh") or shutil.which("powershell")
        caps.append(
            Capability(
                "powershell",
                ps is not None,
                Path(ps).name if ps else "",
                "PowerShell no encontrado en el PATH",
            )
        )
        try:
            import win32gui  # noqa: F401

            caps.append(Capability("windows", True, "pywin32"))
        except ImportError:
            caps.append(Capability("windows", False, "", "pip install pywin32 para control de ventanas"))
        caps.append(Capability("clipboard", ps is not None, "Get/Set-Clipboard", "requiere PowerShell 5+"))
        caps.append(Capability("notify", ps is not None, "toast/balloon", "requiere PowerShell 5+"))
        caps.append(
            Capability(
                "volume",
                self.which("nircmd") is not None,
                "nircmd",
                "instala nircmd o un helper de CoreAudio (pycaw) para control de volumen",
            )
        )
        caps.append(Capability("brightness", True, "WMI WmiMonitorBrightnessMethods"))
        caps.append(
            Capability(
                "packages",
                self.which("winget") is not None,
                "winget",
                "winget no disponible (Windows 10 antiguo)",
            )
        )
        caps.append(Capability("services", True, "Get-Service"))
        caps.append(
            Capability(
                "not_root",
                not _is_admin(),
                "admin",
                "JarvisM está corriendo como administrador: no debe hacerlo (docs/03 §1)",
            )
        )
        return caps

    # ------------------------------------------------------------------ #
    def system_info(self) -> SystemInfo:
        os_info = _ps_json(
            "Get-CimInstance Win32_OperatingSystem | "
            "Select-Object Caption,Version,BuildNumber,LastBootUpTime,TotalVisibleMemorySize,FreePhysicalMemory"  # noqa: E501
        )
        cpu = _ps_json(
            "Get-CimInstance Win32_Processor | Select-Object -First 1 Name,NumberOfLogicalProcessors"
        )
        os_name = "Windows"
        os_version = platform.release()
        memory = None
        if isinstance(os_info, dict):
            os_name = os_info.get("Caption") or os_name
            os_version = f"{os_info.get('Version', '')} (build {os_info.get('BuildNumber', '')})".strip()
            total = float(os_info.get("TotalVisibleMemorySize") or 0) / 1024
            free = float(os_info.get("FreePhysicalMemory") or 0) / 1024
            memory = MemoryInfo(
                total_mb=round(total, 1),
                available_mb=round(free, 1),
                used_pct=round((total - free) / total * 100, 1) if total else 0.0,
            )
        cpu_count = os.cpu_count() or 1
        cpu_model = ""
        if isinstance(cpu, dict):
            cpu_model = str(cpu.get("Name") or "")
            cpu_count = int(cpu.get("NumberOfLogicalProcessors") or cpu_count)
        return SystemInfo(
            platform=Platform.WINDOWS,
            os_name=os_name,
            os_version=os_version,
            hostname=platform.node(),
            user=getpass.getuser(),
            kernel=platform.version(),
            cpu_count=cpu_count,
            cpu_model=cpu_model,
            memory=memory,
            desktop="Windows Shell",
            display_server="dwm",
            is_root=_is_admin(),
            python=platform.python_version(),
        )

    def disks(self) -> list[Volume]:
        data = _ps_json(
            "Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | "
            "Select-Object DeviceID,FileSystem,Size,FreeSpace"
        )
        out: list[Volume] = []
        if isinstance(data, dict):
            data = [data]
        for row in data or []:
            total = float(row.get("Size") or 0)
            free = float(row.get("FreeSpace") or 0)
            if total <= 0:
                continue
            out.append(
                Volume(
                    mount=str(row.get("DeviceID", "")),
                    device=str(row.get("DeviceID", "")),
                    total_gb=round(total / 1024**3, 2),
                    used_gb=round((total - free) / 1024**3, 2),
                    free_gb=round(free / 1024**3, 2),
                    used_pct=round((total - free) / total * 100, 1),
                    fstype=str(row.get("FileSystem") or ""),
                )
            )
        # Fallback nativo si WMI no responde.
        if not out:
            for letter in "CDEFG":
                root = f"{letter}:\\"
                if not Path(root).exists():
                    continue
                usage = shutil.disk_usage(root)
                out.append(
                    Volume(
                        mount=root,
                        device=root,
                        total_gb=round(usage.total / 1024**3, 2),
                        used_gb=round(usage.used / 1024**3, 2),
                        free_gb=round(usage.free / 1024**3, 2),
                        used_pct=round(usage.used / usage.total * 100, 1),
                    )
                )
        return sorted(out, key=lambda v: v.used_pct, reverse=True)

    def processes(self, top_n: int = 10, sort_by: str = "mem") -> list[Proc]:
        field = "CPU" if sort_by == "cpu" else "WorkingSet64"
        data = _ps_json(
            f"Get-Process | Sort-Object {field} -Descending | Select-Object -First {int(top_n)} "
            "Id,ProcessName,@{n='User';e={$env:USERNAME}},CPU,@{n='MemMB';e={[math]::Round($_.WorkingSet64/1MB,1)}}"
        )
        if isinstance(data, dict):
            data = [data]
        out: list[Proc] = []
        for row in data or []:
            out.append(
                Proc(
                    pid=int(row.get("Id") or 0),
                    name=str(row.get("ProcessName") or ""),
                    user=str(row.get("User") or ""),
                    cpu_pct=float(row.get("CPU") or 0.0),
                    mem_mb=float(row.get("MemMB") or 0.0),
                )
            )
        return out

    def battery(self) -> Battery | None:
        data = _ps_json(
            "Get-CimInstance Win32_Battery | Select-Object BatteryStatus,EstimatedChargeRemaining"
        )
        if not data:
            return None
        if isinstance(data, list):
            data = data[0]
        status = int(data.get("BatteryStatus") or 0)
        return Battery(
            present=True,
            percent=float(data.get("EstimatedChargeRemaining") or 0.0),
            charging=status in {2, 6, 7, 8},
        )

    def temperatures(self) -> dict[str, float]:
        data = _ps_json(
            "Get-CimInstance MSAcpi_ThermalZoneTemperature -Namespace root/wmi | "
            "Select-Object InstanceName,CurrentTemperature"
        )
        if not data:
            return {}
        if isinstance(data, dict):
            data = [data]
        out: dict[str, float] = {}
        for row in data:
            try:
                kelvin_tenths = float(row.get("CurrentTemperature") or 0)
                out[str(row.get("InstanceName") or "thermal")] = round(kelvin_tenths / 10 - 273.15, 1)
            except (TypeError, ValueError):
                continue
        return out

    def network_listeners(self) -> list[dict[str, Any]]:
        ok, out = _ps(
            "Get-NetTCPConnection -State Listen | "
            "Select-Object LocalAddress,LocalPort,OwningProcess | ConvertTo-Json -Compress"
        )
        if not ok:
            return []
        try:
            data = json.loads(out) if out else []
        except json.JSONDecodeError:
            return []
        if isinstance(data, dict):
            data = [data]
        return [
            {
                "proto": "tcp",
                "local": f"{r.get('LocalAddress')}:{r.get('LocalPort')}",
                "process": str(r.get("OwningProcess")),
            }
            for r in data[:50]
        ]

    # ------------------------------------------------------------------ #
    def list_apps(self) -> list[AppInfo]:
        script = (
            "$paths = @('HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths', "
            "'HKLM:\\SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\App Paths');"
            "foreach ($p in $paths) { if (Test-Path $p) { Get-ChildItem $p | ForEach-Object { "
            "$props = Get-ItemProperty $_.PSPath; "
            "[pscustomobject]@{ Name=$_.PSChildName; Executable=$props.'(default)' } } } }"
        )
        data = _ps_json(script)
        if isinstance(data, dict):
            data = [data]
        apps: list[AppInfo] = []
        for row in data or []:
            name = str(row.get("Name") or "")
            exe = str(row.get("Executable") or "")
            if name:
                apps.append(AppInfo(name=name.removesuffix(".exe"), executable=exe, source="App Paths"))
        # Start Menu como segunda fuente (nombres amigables).
        start_ok, out = _ps(
            'Get-ChildItem -Path "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs",'
            '"$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs" -Filter *.lnk -Recurse -ErrorAction SilentlyContinue | '  # noqa: E501
            "Select-Object -ExpandProperty BaseName"
        )
        if start_ok:
            for line in out.splitlines():
                if line.strip() and line.strip() not in {a.name for a in apps}:
                    apps.append(AppInfo(name=line.strip(), source="Start Menu"))
        return sorted(apps, key=lambda a: a.name.lower())[:400]

    def launch(self, app: str, args: list[str] | None = None) -> LaunchResult:
        query = app.strip()
        if not query:
            return LaunchResult(False, app, "nombre de aplicación vacío")
        exe = shutil.which(query) or shutil.which(f"{query}.exe")
        if exe:
            pid, error = spawn_detached([exe, *(args or [])])
            if pid:
                return LaunchResult(True, query, f"lanzado desde PATH: {exe}", pid=pid)
            return LaunchResult(False, query, error)
        ok, out = _ps(
            f"$p = Start-Process -FilePath '{query}' -PassThru -ErrorAction SilentlyContinue; "
            "if ($p) {{ $p.Id }} else {{ 'ERR' }}"
        )
        if ok and out.isdigit():
            return LaunchResult(True, query, "lanzado con Start-Process", pid=int(out))
        return LaunchResult(False, query, f"no encuentro '{query}' ni en App Paths ni en el PATH")

    def windows(self) -> list[WindowInfo]:
        try:
            import win32gui
        except ImportError:
            return []
        result: list[WindowInfo] = []

        def collector(hwnd: int, _: Any) -> None:
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    result.append(WindowInfo(id=str(hwnd), title=title))

        win32gui.EnumWindows(collector, None)
        return result[:100]

    def active_window(self) -> WindowInfo | None:
        try:
            import win32gui
        except ImportError:
            return None
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        return WindowInfo(id=str(hwnd), title=win32gui.GetWindowText(hwnd))

    def focus_window(self, title_pattern: str) -> bool:
        try:
            import win32gui
        except ImportError:
            return False
        target: list[int] = []

        def match(hwnd: int, _: Any) -> None:
            if title_pattern.lower() in win32gui.GetWindowText(hwnd).lower():
                target.append(hwnd)

        win32gui.EnumWindows(match, None)
        if not target:
            return False
        try:
            win32gui.SetForegroundWindow(target[0])
            return True
        except Exception:
            return False

    def close_window(self, title_pattern: str) -> bool:
        try:
            import win32con
            import win32gui
        except ImportError:
            return False
        closed = False

        def match(hwnd: int, _: Any) -> None:
            nonlocal closed
            if title_pattern.lower() in win32gui.GetWindowText(hwnd).lower():
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                closed = True

        win32gui.EnumWindows(match, None)
        return closed

    # ------------------------------------------------------------------ #
    def set_volume(self, percent: int) -> bool:
        percent = max(0, min(100, percent))
        if nircmd := self.which("nircmd"):
            return run_command([nircmd, "setsysvolume", str(int(percent * 655.35))]).ok
        try:
            from ctypes import POINTER, cast

            import comtypes
            import pycaw.pycaw as pycaw
        except ImportError:
            return False
        try:  # pragma: no cover - requiere Windows con audio
            comtypes.CoInitialize()
            devices = pycaw.AudioUtilities.GetSpeakers()
            interface = devices.Activate(pycaw.IAudioEndpointVolume_clsid, comtypes.CLSCTX_ALL, None)
            volume = cast(interface, POINTER(pycaw.IAudioEndpointVolume))
            volume.SetMasterVolumeLevelScalar(percent / 100, None)
            return True
        except Exception:
            return False

    def get_volume(self) -> int | None:
        """Solo disponible con `pycaw` instalado; nircmd no expone la lectura."""
        try:
            from ctypes import POINTER, cast

            import comtypes
            import pycaw.pycaw as pycaw
        except ImportError:
            return None
        try:  # pragma: no cover - requiere Windows con audio
            comtypes.CoInitialize()
            devices = pycaw.AudioUtilities.GetSpeakers()
            interface = devices.Activate(pycaw.IAudioEndpointVolume_clsid, comtypes.CLSCTX_ALL, None)
            volume = cast(interface, POINTER(pycaw.IAudioEndpointVolume))
            return round(volume.GetMasterVolumeLevelScalar() * 100)
        except Exception:
            return None

    def mute(self, value: bool) -> bool:
        if nircmd := self.which("nircmd"):
            return run_command([nircmd, "mutesysvolume", "1" if value else "0"]).ok
        return False

    def set_brightness(self, percent: int) -> bool:
        percent = max(0, min(100, percent))
        ok, _ = _ps(
            "$m = Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorBrightnessMethods -ErrorAction SilentlyContinue; "  # noqa: E501
            f"if ($m) {{ Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{{Timeout=1;Brightness={percent}}} | Out-Null; 'ok' }} else {{ 'err' }}"  # noqa: E501
        )
        return ok

    def notify(self, title: str, body: str, *, level: Severity = Severity.INFO) -> bool:
        safe_title = title.replace("'", "''")[:120]
        safe_body = body.replace("'", "''")[:400]
        script = (
            "[reflection.assembly]::loadwithpartialname('System.Windows.Forms') | Out-Null;"
            "[reflection.assembly]::loadwithpartialname('System.Drawing') | Out-Null;"
            "$n = New-Object System.Windows.Forms.NotifyIcon;"
            "$n.Icon = [System.Drawing.SystemIcons]::Information;"
            "$n.BalloonTipIcon = "
            f"'{'Error' if level is Severity.CRITICAL else 'Warning' if level is Severity.WARNING else 'Info'}';"  # noqa: E501
            "$n.BalloonTipTitle = '" + safe_title + "';"
            "$n.BalloonTipText = '" + safe_body + "';"
            "$n.Visible = $true; $n.ShowBalloonTip(8000);"
            "Start-Sleep -Milliseconds 200; $n.Dispose()"
        )
        ok, _ = _ps(script, timeout=15)
        return ok

    def clipboard_get(self) -> str:
        ok, out = _ps("Get-Clipboard -Raw -ErrorAction SilentlyContinue")
        return out if ok else ""

    def clipboard_set(self, text: str) -> bool:
        # Set-Clipboard no lee stdin de forma fiable en todas las versiones de
        # PowerShell: pasamos el texto como literal con las comillas escapadas.
        escaped = text.replace("'", "''")
        ok, _ = _ps(f"Set-Clipboard -Value '{escaped}'")
        return ok

    # ------------------------------------------------------------------ #
    def pending_updates(self) -> UpdateSummary:
        if self.which("winget"):
            ok, out = run_command_safe(["winget", "upgrade", "--include-unknown"], timeout=90)
            if ok:
                lines = [ln for ln in out.splitlines() if ln.strip() and not ln.startswith(("Name", "---"))]
                return UpdateSummary(
                    package_manager="winget",
                    total=max(0, len(lines)),
                    packages=lines[:30],
                    detail=f"{len(lines)} actualizaciones disponibles vía winget",
                )
        # Sin winget: la consulta COM de Windows Update puede tardar ~30 s y
        # bloquea el turno, así que se deja para el watchdog (Fase 4), no para
        # una petición interactiva.
        return UpdateSummary(
            package_manager="windows-update",
            detail=(
                "winget no disponible. La consulta COM de Windows Update se hace desde el "
                "watchdog (Fase 4), no en un turno interactivo, porque tarda ~30 s."
            ),
        )


def run_command_safe(cmd: list[str], *, timeout: float = 25.0) -> tuple[bool, str]:
    result = run_command(cmd, timeout=timeout)
    return result.ok, result.stdout


def _is_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False
