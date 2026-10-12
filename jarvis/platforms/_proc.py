"""Ejecución de procesos compartida por los adapters (ADR-0004).

Único punto del proyecto, junto a `skills/shell.py`, donde se permite `subprocess`.
Nunca `shell=True`: evita inyección por metacaracteres y hace que el comportamiento
sea idéntico en los tres sistemas.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_TIMEOUT = 8.0


class CommandResult:
    __slots__ = ("code", "stderr", "stdout")

    def __init__(self, code: int, stdout: str, stderr: str) -> None:
        self.code = code
        self.stdout = stdout
        self.stderr = stderr

    @property
    def ok(self) -> bool:
        return self.code == 0

    def __iter__(self):  # compatibilidad con desempaquetado (code, out, err)
        return iter((self.code, self.stdout, self.stderr))

    def __repr__(self) -> str:  # pragma: no cover
        return f"CommandResult(code={self.code}, stdout={self.stdout[:60]!r})"


def run_command(
    cmd: list[str],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    cwd: str | Path | None = None,
    stdin_text: str | None = None,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Ejecuta `cmd` y devuelve código/salida/error sin lanzar excepciones."""
    if not cmd or not cmd[0]:
        return CommandResult(127, "", "comando vacío")
    first = cmd[0]
    if not Path(first).is_absolute() and shutil.which(first) is None:
        return CommandResult(127, "", f"binario no encontrado: {first}")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd else None,
            input=stdin_text,
            env=env,
            check=False,
        )
        return CommandResult(proc.returncode, proc.stdout, proc.stderr)
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", f"timeout tras {timeout}s")
    except OSError as exc:
        return CommandResult(1, "", str(exc))


def spawn_detached(cmd: list[str]) -> tuple[int | None, str]:
    """Lanza un proceso desvinculado de la sesión (para abrir apps)."""
    if not cmd or not cmd[0]:
        return None, "comando vacío"
    first = cmd[0]
    if not Path(first).is_absolute() and shutil.which(first) is None:
        return None, f"binario no encontrado: {first}"
    kwargs: dict[str, Any] = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "close_fds": True,
    }
    import sys

    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)
        return proc.pid, ""
    except OSError as exc:
        return None, str(exc)


def which(*binaries: str) -> str | None:
    for binary in binaries:
        if found := shutil.which(binary):
            return found
    return None
