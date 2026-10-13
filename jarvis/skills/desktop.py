"""Skills de escritorio: portapapeles, volumen, brillo, notificaciones y notas."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from jarvis.safety.policy import RiskTier, redact
from jarvis.skills.base import Skill, SkillResult


class ClipboardGetSkill(Skill):
    name = "clipboard.get"
    description = (
        "Lee el contenido actual del portapapeles del sistema. Úsalo cuando el usuario dice "
        "'lo que acabo de copiar', 'pégalo aquí', 'revisa mi clipboard'. Los secretos detectados "
        "se enmascaran automáticamente."
    )
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    tier = RiskTier.T0

    def execute(self) -> SkillResult:
        text = self.adapter.clipboard_get()
        if not text:
            return SkillResult.failure("El portapapeles está vacío (o no puedo leerlo en este entorno).")
        clean, hits = redact(text)
        note = f" [se enmascararon {hits} posibles secretos]" if hits else ""
        preview = clean[:2000]
        return SkillResult.success(
            f"Portapapeles ({len(text)} caracteres){note}:\n{preview}",
            data={"chars": len(text), "redactions": hits},
            llm=preview,
        )


class ClipboardSetSkill(Skill):
    name = "clipboard.set"
    description = "Copia un texto al portapapeles del sistema. Úsalo para 'copia esto'."
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 100_000}},
        "required": ["text"],
        "additionalProperties": False,
    }
    tier = RiskTier.T1
    undoable = True

    def execute(self, text: str) -> SkillResult:
        previous = self.adapter.clipboard_get()
        if not self.adapter.clipboard_set(text):
            return SkillResult.failure("No pude escribir en el portapapeles en este entorno.")

        def undo(prev: str = previous) -> SkillResult:
            if prev:
                self.adapter.clipboard_set(prev)
                return SkillResult(ok=True, message_for_user="Restauré el portapapeles anterior.")
            return SkillResult(ok=True, message_for_user="El portapapeles anterior estaba vacío.")

        return SkillResult.success(f"Copiado ({len(text)} caracteres).", data={"chars": len(text)}, undo=undo)


class VolumeSkill(Skill):
    name = "media.volume"
    description = (
        "Ajusta el volumen del sistema a un porcentaje (0-100), o lo sube/baja en pasos. "
        "Úsalo para 'sube el volumen', 'ponlo al 30', 'baja el sonido'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "percent": {
                "type": "integer",
                "minimum": 0,
                "maximum": 150,
                "description": "Volumen absoluto a fijar.",
            },
            "delta": {
                "type": "integer",
                "minimum": -100,
                "maximum": 100,
                "description": "Cambio relativo (p. ej. -10 para bajar 10 puntos).",
            },
            "mute": {"type": "boolean", "description": "Silenciar (true) o quitar el silencio (false)."},
        },
        "additionalProperties": False,
    }
    tier = RiskTier.T1
    undoable = True

    def execute(
        self, percent: int | None = None, delta: int | None = None, mute: bool | None = None
    ) -> SkillResult:
        if mute is not None:
            if not self.adapter.mute(mute):
                return SkillResult.failure("No puedo controlar el silencio en este entorno.")
            return SkillResult.success("Silenciado." if mute else "Sonido activado.")

        current = self.adapter.get_volume()
        if percent is None and delta is None:
            if current is None:
                return SkillResult.failure("No puedo leer el volumen actual en este entorno.")
            return SkillResult.success(f"El volumen está al {current}%.")

        target = percent if percent is not None else max(0, min(150, (current or 50) + (delta or 0)))
        if not self.adapter.set_volume(target):
            cap = next((c for c in self.adapter.capabilities() if c.name == "volume"), None)
            hint = f" ({cap.hint})" if cap and cap.hint else ""
            return SkillResult.failure(f"No pude ajustar el volumen{hint}.")

        def undo(prev: int | None = current) -> SkillResult:
            if prev is None:
                return SkillResult(ok=False, message_for_user="No conocía el volumen anterior.")
            self.adapter.set_volume(prev)
            return SkillResult(ok=True, message_for_user=f"Volumen restaurado al {prev}%.")

        return SkillResult.success(
            f"Volumen al {target}%.", data={"percent": target, "previous": current}, undo=undo
        )


class BrightnessSkill(Skill):
    name = "media.brightness"
    description = "Ajusta el brillo de la pantalla a un porcentaje (0-100)."
    parameters = {
        "type": "object",
        "properties": {"percent": {"type": "integer", "minimum": 0, "maximum": 100}},
        "required": ["percent"],
        "additionalProperties": False,
    }
    tier = RiskTier.T1

    def execute(self, percent: int) -> SkillResult:
        if not self.adapter.set_brightness(percent):
            cap = next((c for c in self.adapter.capabilities() if c.name == "brightness"), None)
            hint = f" ({cap.hint})" if cap and cap.hint else ""
            return SkillResult.failure(f"No pude ajustar el brillo{hint}.")
        return SkillResult.success(f"Brillo al {percent}%.")


class NotifySkill(Skill):
    name = "ui.notify"
    description = (
        "Muestra una notificación nativa del sistema operativo con título y cuerpo. Úsalo para "
        "avisos que el usuario debe ver aunque no esté mirando la terminal."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 120},
            "body": {"type": "string", "minLength": 1, "maxLength": 500},
            "level": {"type": "string", "enum": ["info", "warning", "critical"], "default": "info"},
        },
        "required": ["title", "body"],
        "additionalProperties": False,
    }
    tier = RiskTier.T1

    def execute(self, title: str, body: str, level: str = "info") -> SkillResult:
        from jarvis.platforms.base import Severity

        if not self.adapter.notify(title, body, level=Severity(level)):
            return SkillResult.failure("No hay sistema de notificaciones disponible.")
        return SkillResult.success(f"Notificación enviada: {title}")


class NoteCreateSkill(Skill):
    name = "notes.create"
    description = (
        "Guarda una nota en Markdown dentro de la carpeta de trabajo de Jarvis. Úsalo para "
        "'apunta que...', 'recuérdame esto', 'guarda esta idea'. Las notas se listan con notes.list."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 120},
            "body": {"type": "string", "minLength": 1, "maxLength": 20_000},
            "tags": {"type": "array", "items": {"type": "string"}, "default": []},
        },
        "required": ["title", "body"],
        "additionalProperties": False,
    }
    tier = RiskTier.T1  # escritura dentro de la jaula de rutas
    undoable = True

    def execute(self, title: str, body: str, tags: list[str] | None = None) -> SkillResult:
        notes_dir = self.ctx.workdir / "notes"
        notes_dir.mkdir(parents=True, exist_ok=True)
        slug = "".join(c if c.isalnum() or c in "-_ " else "-" for c in title).strip().replace(" ", "-")[:60]
        filename = f"{time.strftime('%Y%m%d-%H%M%S')}-{slug or 'nota'}.md"
        target = notes_dir / filename
        clean_body, hits = redact(body)
        content = "\n".join(
            [
                f"# {title}",
                "",
                f"- Creada: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                f"- Etiquetas: {', '.join(tags) if tags else '-'}",
                "",
                clean_body,
                "",
            ]
        )
        target.write_text(content, encoding="utf-8")
        note = f" (se enmascararon {hits} posibles secretos)" if hits else ""
        return SkillResult.success(
            f"Nota guardada en {target}{note}",
            data={"path": str(target), "bytes": len(content)},
            undo=lambda: _delete_note(target),
        )


def _delete_note(path: Path) -> SkillResult:
    try:
        path.unlink(missing_ok=True)
        return SkillResult(ok=True, message_for_user=f"Eliminé la nota {path.name}.")
    except OSError as exc:
        return SkillResult(ok=False, message_for_user=f"No pude deshacer: {exc}")


class NoteListSkill(Skill):
    name = "notes.list"
    description = "Lista las notas guardadas por Jarvis, con fecha y tamaño."
    parameters = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 20}},
        "additionalProperties": False,
    }
    tier = RiskTier.T0

    def execute(self, limit: int = 20) -> SkillResult:
        notes_dir = self.ctx.workdir / "notes"
        if not notes_dir.is_dir():
            return SkillResult.success("Aún no hay notas guardadas.")
        files = sorted(notes_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
        if not files:
            return SkillResult.success("Aún no hay notas guardadas.")
        rows: list[dict[str, Any]] = []
        lines = []
        for path in files:
            stat = path.stat()
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))
            lines.append(f"  {when}  {stat.st_size:>6} B  {path.name}")
            rows.append({"name": path.name, "path": str(path), "modified": when, "bytes": stat.st_size})
        return SkillResult.success(f"{len(files)} notas:\n" + "\n".join(lines), data=rows)
