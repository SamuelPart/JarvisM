"""Skills de archivos: buscar, abrir, leer. Nunca borran sin confirmación."""

from __future__ import annotations

import fnmatch
import os
import sys
import time
from pathlib import Path
from typing import Any

from jarvis.config.settings import expand_path
from jarvis.safety.policy import RiskTier
from jarvis.skills.base import Skill, SkillResult

SKIP_DIRS = {
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
    ".npm",
    ".cargo",
    "dist",
    "build",
    ".tox",
    ".gradle",
    ".idea",
    "target",
    ".next",
    ".nuxt",
}


class SearchFilesSkill(Skill):
    name = "files.search"
    description = (
        "Busca archivos por patrón glob (p. ej. '*.pdf', 'informe*.docx') dentro de una carpeta, "
        "opcionalmente filtrando por tamaño mínimo y por antigüedad. Úsalo para 'busca los pdf de', "
        "'dónde está el archivo', 'qué .log hay aquí'. Solo lectura."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "minLength": 1, "description": "Patrón glob, p. ej. '*.py'."},
            "path": {"type": "string", "default": ".", "description": "Carpeta raíz de la búsqueda."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
            "max_depth": {"type": "integer", "minimum": 1, "maximum": 12, "default": 6},
            "min_size_kb": {"type": "number", "minimum": 0, "description": "Tamaño mínimo en KB."},
            "modified_within_days": {
                "type": "integer",
                "minimum": 1,
                "description": "Solo archivos recientes.",
            },
        },
        "required": ["pattern"],
        "additionalProperties": False,
    }
    tier = RiskTier.T0

    def execute(
        self,
        pattern: str,
        path: str = ".",
        limit: int = 25,
        max_depth: int = 6,
        min_size_kb: float | None = None,
        modified_within_days: int | None = None,
    ) -> SkillResult:
        root = expand_path(path)
        if self.ctx.policy.is_excluded_path(root):
            return SkillResult.failure(f"La carpeta {root} está protegida por la política de privacidad.")
        if not root.exists():
            return SkillResult.failure(f"No existe la ruta {root}")
        if not root.is_dir():
            return SkillResult.success(str(root), data={"path": str(root), "type": "file"})

        started = time.perf_counter()
        cutoff = time.time() - modified_within_days * 86_400 if modified_within_days else None
        min_bytes = min_size_kb * 1024 if min_size_kb else None
        matches: list[dict[str, Any]] = []
        scanned = 0

        def walk(directory: Path, depth: int) -> None:
            nonlocal scanned
            if depth > max_depth or len(matches) >= limit:
                return
            try:
                entries = list(os.scandir(directory))
            except (PermissionError, OSError):
                return
            for entry in entries:
                scanned += 1
                if scanned > 200_000:  # tope duro para no colgar el turno
                    return
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in SKIP_DIRS or entry.name.startswith("."):
                        continue
                    walk(Path(entry.path), depth + 1)
                elif fnmatch.fnmatch(entry.name.lower(), pattern.lower()):
                    try:
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if min_bytes and stat.st_size < min_bytes:
                        continue
                    if cutoff and stat.st_mtime < cutoff:
                        continue
                    matches.append(
                        {
                            "path": entry.path,
                            "size_kb": round(stat.st_size / 1024, 1),
                            "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                        }
                    )
                    if len(matches) >= limit:
                        return

        walk(root, 1)
        elapsed = round((time.perf_counter() - started) * 1000)
        if not matches:
            return SkillResult.failure(
                f"Sin resultados para '{pattern}' en {root} ({scanned} entradas exploradas en {elapsed} ms)."
            )
        lines = [f"{m['size_kb']:>10} KB  {m['modified']}  {m['path']}" for m in matches]
        return SkillResult.success(
            f"{len(matches)} coincidencias para '{pattern}' en {root}:\n" + "\n".join(lines),
            data={"matches": matches, "scanned": scanned, "elapsed_ms": elapsed},
        )


class OpenFileSkill(Skill):
    name = "files.open"
    description = (
        "Abre un archivo o carpeta con la aplicación predeterminada del sistema "
        "(xdg-open / start / open). Úsalo para 'abre el informe.pdf', 'abre esta carpeta'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1, "description": "Ruta del archivo o carpeta."}
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    tier = RiskTier.T1  # abrir es reversible, pero delega en una app externa

    def execute(self, path: str) -> SkillResult:
        target = expand_path(path)
        if self.ctx.policy.is_excluded_path(target):
            return SkillResult.failure(f"{target} está protegida por la política de privacidad.")
        if not target.exists():
            return SkillResult.failure(f"No existe {target}")
        opener = {
            "linux": "xdg-open",
            "darwin": "open",
            "windows": "cmd",
        }.get(sys.platform, "xdg-open")
        cmd = [opener, str(target)] if opener != "cmd" else ["cmd", "/c", "start", "", str(target)]
        from jarvis.platforms._proc import spawn_detached

        pid, error = spawn_detached(cmd)
        if pid is None:
            return SkillResult.failure(f"No pude abrir {target}: {error}")
        return SkillResult.success(f"Abriendo {target.name}.", data={"path": str(target), "pid": pid})


class ReadFileSkill(Skill):
    name = "files.read"
    description = (
        "Lee el contenido de un archivo de texto y lo devuelve truncado a un número de bytes. "
        "Úsalo cuando el usuario pide resumir o revisar un archivo concreto. NO lo uses con "
        "binarios ni con rutas de configuración sensible."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "minLength": 1},
            "max_bytes": {"type": "integer", "minimum": 1, "maximum": 200_000, "default": 20_000},
        },
        "required": ["path"],
        "additionalProperties": False,
    }
    tier = RiskTier.T0

    def execute(self, path: str, max_bytes: int = 20_000) -> SkillResult:
        target = expand_path(path)
        if self.ctx.policy.is_excluded_path(target):
            return SkillResult.failure(f"{target} está protegida y no puedo leerla.")
        if not target.is_file():
            return SkillResult.failure(f"{target} no es un archivo legible.")
        try:
            raw = target.read_bytes()[:max_bytes]
        except OSError as exc:
            return SkillResult.failure(f"No pude leer {target}: {exc}")
        text, redactions = _redact(raw.decode("utf-8", errors="replace"))
        note = f" (se enmascararon {redactions} posibles secretos)" if redactions else ""
        truncated = " [TRUNCADO]" if target.stat().st_size > max_bytes else ""
        return SkillResult.success(
            f"{target.name}{truncated}{note}:\n{text}",
            data={"path": str(target), "bytes": len(raw), "redactions": redactions},
            llm=text,
        )


def _redact(text: str) -> tuple[str, int]:
    from jarvis.safety.policy import redact

    if not text:
        return text, 0
    return redact(text)
