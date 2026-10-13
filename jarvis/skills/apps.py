"""Skills de aplicaciones y ventanas."""

from __future__ import annotations

from dataclasses import asdict

from jarvis.safety.policy import RiskTier
from jarvis.skills.base import Skill, SkillResult

# Aliases en español -> candidatos por plataforma. Se amplía con el uso (Fase 5).
ALIASES: dict[str, tuple[str, ...]] = {
    "navegador": ("firefox", "firefox-esr", "google-chrome", "chromium", "brave", "edge"),
    "chrome": ("google-chrome", "chrome", "chromium"),
    "explorador": ("nautilus", "dolphin", "thunar", "files", "explorer", "finder"),
    "archivos": ("nautilus", "dolphin", "thunar", "files", "explorer", "finder"),
    "terminal": ("gnome-terminal", "konsole", "xfce4-terminal", "xterm", "wt", "alacritty", "kitty"),
    "editor": ("code", "codium", "gedit", "kate", "mousepad", "subl", "notepad", "textedit"),
    "correo": ("thunderbird", "evolution", "geary", "outlook", "mail"),
    "calculadora": ("gnome-calculator", "galculator", "kcalc", "calc", "calculator"),
    "musica": ("spotify", "rhythmbox", "music", "amarok"),
    "música": ("spotify", "rhythmbox", "music", "amarok"),
    "ajustes": (
        "gnome-control-center",
        "systemsettings",
        "xfce4-settings-manager",
        "ms-settings:",
        "system preferences",
    ),
    "monitor": ("gnome-system-monitor", "ksysguard", "xfce4-taskmanager", "taskmgr", "activity monitor"),
}


def resolve_alias(name: str) -> list[str]:
    """Devuelve la lista de candidatos a probar para un nombre dado."""
    key = name.strip().lower()
    if key in ALIASES:
        return list(ALIASES[key])
    return [name.strip()]


class ListAppsSkill(Skill):
    name = "apps.list"
    description = (
        "Lista las aplicaciones instaladas y localizables en este sistema (entradas .desktop en "
        "Linux, App Paths y menú Inicio en Windows, bundles en macOS). Úsalo antes de intentar "
        "abrir una app cuyo nombre exacto desconoces, o cuando el usuario pregunte "
        "'qué programas tengo'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "filter": {"type": "string", "description": "Opcional: subcadena para filtrar la lista."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 300, "default": 40},
        },
        "additionalProperties": False,
    }
    tier = RiskTier.T0

    def execute(self, filter: str | None = None, limit: int = 40) -> SkillResult:
        apps = self.adapter.list_apps()
        if filter:
            needle = filter.lower()
            apps = [a for a in apps if needle in a.name.lower() or needle in a.executable.lower()]
        if not apps:
            return SkillResult.failure(
                f"No encuentro aplicaciones{f' que coincidan con {filter!r}' if filter else ''}."
            )
        shown = apps[:limit]
        text = f"{len(apps)} aplicaciones{f' ({len(shown)} mostradas)' if len(apps) > limit else ''}:\n"
        text += ", ".join(a.name for a in shown)
        return SkillResult.success(text, data=[asdict(a) for a in shown])


class LaunchAppSkill(Skill):
    name = "apps.launch"
    description = (
        "Abre una aplicación por nombre. Acepta nombres comunes en español ('navegador', "
        "'terminal', 'archivos', 'editor') y los resuelve a la app instalada correspondiente. "
        "Si no existe, devuelve error en vez de inventar una alternativa."
    )
    parameters = {
        "type": "object",
        "properties": {
            "app": {"type": "string", "minLength": 1, "description": "Nombre de la aplicación a abrir."},
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Argumentos opcionales para la aplicación.",
                "default": [],
            },
        },
        "required": ["app"],
        "additionalProperties": False,
    }
    tier = RiskTier.T1  # reversible: se puede cerrar la ventana
    undoable = True

    def execute(self, app: str, args: list[str] | None = None) -> SkillResult:
        candidates = resolve_alias(app)
        attempts: list[str] = []
        for candidate in candidates:
            result = self.adapter.launch(candidate, args or [])
            attempts.append(f"{candidate}: {result.detail}")
            if result.ok:

                def undo(name: str = candidate) -> SkillResult:
                    closed = self.adapter.close_window(name)
                    return SkillResult(
                        ok=closed,
                        message_for_user=f"Cerré {name}."
                        if closed
                        else f"No pude cerrar {name} automáticamente.",
                    )

                self.ctx.bus.publish("app.launched", source=self.name, app=candidate, pid=result.pid)
                return SkillResult(
                    ok=True,
                    message_for_user=f"Abriendo {candidate}.",
                    message_for_llm=f"Aplicación '{candidate}' lanzada. {result.detail}",
                    data={"app": candidate, "pid": result.pid, "attempts": attempts},
                    undo=undo if result.pid else None,
                )
        return SkillResult.failure(
            f"No pude abrir '{app}'. Probé: {'; '.join(attempts)}. "
            "Usa apps.list para ver los nombres disponibles.",
            llm=f"apps.launch falló para '{app}'. Intentos: {attempts}",
        )


class ListWindowsSkill(Skill):
    name = "windows.list"
    description = "Lista las ventanas abiertas ahora mismo, con su título."
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}
    tier = RiskTier.T0

    def execute(self) -> SkillResult:
        windows = self.adapter.windows()
        if not windows:
            cap = next((c for c in self.adapter.capabilities() if c.name == "windows"), None)
            hint = f" ({cap.hint})" if cap and cap.hint else ""
            return SkillResult.failure(f"No puedo listar ventanas en este entorno{hint}.")
        lines = [f"  {w.id or '-':<12} {w.title[:80]}" for w in windows[:40]]
        return SkillResult.success(
            f"{len(windows)} ventanas abiertas:\n" + "\n".join(lines), data=[asdict(w) for w in windows[:40]]
        )


class FocusWindowSkill(Skill):
    name = "windows.focus"
    description = (
        "Trae al frente la ventana cuyo título contenga el patrón dado. Úsalo para "
        "'ve a la ventana de X', 'cambia al navegador'."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "description": "Subcadena del título de la ventana."}
        },
        "required": ["title"],
        "additionalProperties": False,
    }
    tier = RiskTier.T1

    def execute(self, title: str) -> SkillResult:
        if self.adapter.focus_window(title):
            return SkillResult.success(f"Listo, te llevo a la ventana de '{title}'.")
        return SkillResult.failure(f"No encuentro ninguna ventana que contenga '{title}'.")


class CloseWindowSkill(Skill):
    name = "windows.close"
    description = (
        "Cierra la ventana cuyo título contenga el patrón. Puede perder cambios sin guardar, "
        "por eso requiere confirmación del usuario."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1, "description": "Subcadena del título de la ventana."}
        },
        "required": ["title"],
        "additionalProperties": False,
    }
    tier = RiskTier.T2  # puede descartar trabajo sin guardar
    undoable = False

    def execute(self, title: str) -> SkillResult:
        if self.adapter.close_window(title):
            return SkillResult.success(f"Cerrada la ventana de '{title}'.")
        return SkillResult.failure(f"No pude cerrar la ventana de '{title}'.")
