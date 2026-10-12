"""Fixtures compartidas: adapter falso, settings aislados y proveedor simulado.

Regla: ningún test toca el sistema real, la red ni el HOME del usuario. Todo se
inyecta (ADR-0004), que es precisamente para lo que existe el `OSAdapter`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jarvis.config.settings import Settings
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
from jarvis.providers.base import (
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    ToolCall,
    Usage,
)
from jarvis.skills.base import ApprovalHandler


class FakeAdapter(OSAdapter):
    """Adapter determinista con datos controlados por el test."""

    platform = Platform.LINUX

    def __init__(self) -> None:
        self.launched: list[tuple[str, list[str]]] = []
        self.clipboard = "contenido inicial del portapapeles"
        self.notifications: list[tuple[str, str, str]] = []
        self.focus_calls: list[str] = []
        self.volumes: list[int] = []
        self.capability_overrides: dict[str, bool] = {}
        self.disk_used_pct = 42.0
        self.ram_used_pct = 30.0
        self.temperature_c = 45.0
        self.battery_pct: float | None = None
        self.launch_ok = True
        self.update_summary = UpdateSummary(package_manager="fake", total=0, detail="al día")

    # -- capacidades ------------------------------------------------------ #
    def capabilities(self) -> list[Capability]:
        base = [
            Capability("windows", True, "fake"),
            Capability("notify", True, "fake"),
            Capability("clipboard", True, "fake"),
            Capability("volume", True, "fake"),
            Capability("brightness", True, "fake"),
            Capability("sensors", True, "fake"),
            Capability("packages", True, "fake"),
            Capability("not_root", True, "uid=1000"),
        ]
        for name, available in self.capability_overrides.items():
            base.append(Capability(name, available, "fake", "" if available else "instala algo"))
        return base

    # -- sistema ---------------------------------------------------------- #
    def system_info(self) -> SystemInfo:
        return SystemInfo(
            platform=Platform.LINUX,
            os_name="TestLinux",
            os_version="1.0",
            hostname="testhost",
            user="tester",
            kernel="6.0.0-test",
            cpu_count=4,
            cpu_model="FakeCPU 4-core",
            load_avg=(0.5, 0.4, 0.3),
            uptime_s=7200.0,
            memory=MemoryInfo(
                total_mb=16384.0,
                available_mb=11468.8,
                used_pct=self.ram_used_pct,
                swap_total_mb=2048.0,
                swap_used_pct=5.0,
            ),
            desktop="XFCE",
            display_server="x11",
            python="3.11.0",
        )

    def disks(self) -> list[Volume]:
        return [
            Volume(
                mount="/",
                device="/dev/fake1",
                total_gb=100.0,
                used_gb=round(100 * self.disk_used_pct / 100, 2),
                free_gb=round(100 - 100 * self.disk_used_pct / 100, 2),
                used_pct=self.disk_used_pct,
                fstype="ext4",
            )
        ]

    def processes(self, top_n: int = 10, sort_by: str = "mem") -> list[Proc]:
        procs = [
            Proc(pid=100, name="firefox", user="tester", cpu_pct=25.0, mem_mb=900.0),
            Proc(pid=101, name="python3", user="tester", cpu_pct=60.0, mem_mb=300.0),
            Proc(pid=1, name="systemd", user="root", cpu_pct=0.1, mem_mb=12.0),
        ]
        key = (lambda p: p.cpu_pct) if sort_by == "cpu" else (lambda p: p.mem_mb)
        return sorted(procs, key=key, reverse=True)[:top_n]

    def battery(self) -> Battery | None:
        if self.battery_pct is None:
            return None
        return Battery(present=True, percent=self.battery_pct, charging=False, seconds_remaining=3600)

    def temperatures(self) -> dict[str, float]:
        return {"x86_pkg_temp": self.temperature_c}

    def network_listeners(self) -> list[dict[str, object]]:
        return [{"proto": "tcp", "local": "127.0.0.1:8765", "process": "jarvis"}]

    # -- apps ------------------------------------------------------------- #
    def list_apps(self) -> list[AppInfo]:
        return [
            AppInfo(name="Firefox", executable="firefox", source="fake", categories=["Network"]),
            AppInfo(name="Terminal", executable="xfce4-terminal", source="fake"),
        ]

    def launch(self, app: str, args: list[str] | None = None) -> LaunchResult:
        self.launched.append((app, args or []))
        if not self.launch_ok:
            return LaunchResult(False, app, "fallo simulado")
        return LaunchResult(True, app, f"lanzado {app}", pid=4242)

    def windows(self) -> list[WindowInfo]:
        return [WindowInfo(id="0x1", title="Firefox — Documentación"), WindowInfo(id="0x2", title="Terminal")]

    def focus_window(self, title_pattern: str) -> bool:
        self.focus_calls.append(title_pattern)
        return True

    def close_window(self, title_pattern: str) -> bool:
        return True

    # -- escritorio -------------------------------------------------------- #
    def set_volume(self, percent: int) -> bool:
        self.volumes.append(percent)
        return True

    def get_volume(self) -> int | None:
        return self.volumes[-1] if self.volumes else 50

    def mute(self, value: bool) -> bool:
        return True

    def set_brightness(self, percent: int) -> bool:
        return True

    def notify(self, title: str, body: str, *, level: Severity = Severity.INFO) -> bool:
        self.notifications.append((title, body, level.value))
        return True

    def clipboard_get(self) -> str:
        return self.clipboard

    def clipboard_set(self, text: str) -> bool:
        self.clipboard = text
        return True

    def pending_updates(self) -> UpdateSummary:
        return self.update_summary


class ScriptedProvider(LLMProvider):
    """Proveedor que devuelve respuestas predefinidas en orden."""

    name = "scripted"
    supports_tools = True

    def __init__(self, responses: list[CompletionResult]) -> None:
        super().__init__(base_url="http://fake", api_key="fake")
        self.responses = list(responses)
        self.requests: list[CompletionRequest] = []

    def available(self) -> tuple[bool, str]:
        return True, ""

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.requests.append(request)
        if not self.responses:
            return CompletionResult(text="(sin más respuestas)", provider=self.name, model=request.model)
        result = self.responses.pop(0)
        result.provider = self.name
        result.model = request.model
        if result.usage.total == 0:
            result.usage = Usage(input_tokens=100, output_tokens=50)
        return result


@pytest.fixture()
def fake_adapter() -> FakeAdapter:
    return FakeAdapter()


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Configuración aislada: nada toca el HOME real del usuario."""
    cfg = Settings()
    cfg.data_dir = tmp_path / "data"
    cfg.config_dir = tmp_path / "config"
    cfg.log_dir = tmp_path / "log"
    cfg.policy.jail_roots = [str(tmp_path / "workspace")]
    cfg.policy.shell_allowlist = ["ls", "echo", "git", "cat", "ps", "df"]
    cfg.policy.approval_timeout_s = 1
    cfg.watchdog.quiet_hours = []
    cfg.ensure_dirs()
    return cfg


@pytest.fixture()
def audit(settings: Settings):
    from jarvis.safety.audit import AuditLog

    log = AuditLog(settings.audit_db)
    yield log
    log.close()


@pytest.fixture()
def tool_call():
    def make(skill: str, **arguments: object) -> ToolCall:
        return ToolCall(id="call_1", skill=skill, arguments=dict(arguments))

    return make


class Approvals(ApprovalHandler):
    """Handler de aprobación programable: registra lo que se le pidió y responde igual."""

    def __init__(self, grant: bool = True) -> None:
        self.grant = grant
        self.seen: list[dict] = []

    def request(self, **kwargs) -> bool:  # type: ignore[override]
        self.seen.append(kwargs)
        return self.grant


@pytest.fixture()
def approvals() -> Approvals:
    return Approvals()
