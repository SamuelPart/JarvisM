"""Contrato de skill y registro (ADR-0002).

Un skill es la unidad mínima de capacidad. Declara:
  - qué hace y cuándo usarlo (texto que ve el LLM),
  - su esquema de parámetros (validado con JSON Schema antes de ejecutar),
  - su **tier de riesgo** (definido en código, nunca por el modelo),
  - en qué plataformas existe.

Añadir una capacidad nueva = añadir una clase y registrarla. Cero cambios en el core.
"""

from __future__ import annotations

import abc
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema

from jarvis.config.settings import Settings
from jarvis.core.events import EventBus
from jarvis.platforms.base import OSAdapter
from jarvis.providers.base import ToolSpec
from jarvis.safety.audit import AuditLog
from jarvis.safety.policy import PolicyEngine, RiskTier


class ApprovalHandler(abc.ABC):
    """Interfaz de aprobación. La implementa la CLI, la TUI y el HUD."""

    @abc.abstractmethod
    def request(
        self,
        *,
        skill: str,
        arguments: dict[str, Any],
        tier: RiskTier,
        reasons: list[str],
        typed_confirmation: bool,
        timeout_s: int,
    ) -> bool:
        """True = el usuario autoriza. False = deniega o expira el timeout."""


class AutoApprove(ApprovalHandler):
    """Solo para tests y `--dry-run`: no aprueba nada de T2+."""

    def request(self, **kwargs: Any) -> bool:
        return False


@dataclass(slots=True)
class SkillContext:
    """Todo lo que un skill puede necesitar. Se inyecta, nunca se importa."""

    settings: Settings
    adapter: OSAdapter
    policy: PolicyEngine
    audit: AuditLog
    bus: EventBus
    approval: ApprovalHandler = field(default_factory=AutoApprove)
    workspace: Path | None = None
    turn_id: str = ""
    offline: bool = False

    @property
    def workdir(self) -> Path:
        if self.workspace is not None:
            return self.workspace
        from jarvis.config.settings import expand_path

        roots = self.settings.policy.jail_roots
        base = expand_path(roots[0]) if roots else Path.home() / "JarvisWorkspace"
        base.mkdir(parents=True, exist_ok=True)
        return base


@dataclass(slots=True)
class SkillResult:
    ok: bool
    #: Lo que se dice al usuario (breve, natural).
    message_for_user: str = ""
    #: Lo que ve el LLM para decidir el siguiente paso (puede ser más técnico).
    message_for_llm: str = ""
    data: Any = None
    undo: Callable[[], SkillResult] | None = None
    duration_ms: float = 0.0

    @classmethod
    def success(
        cls,
        message: str,
        data: Any = None,
        *,
        llm: str = "",
        undo: Callable[[], SkillResult] | None = None,
    ) -> SkillResult:
        return cls(
            ok=True,
            message_for_user=message,
            message_for_llm=llm or message,
            data=data,
            undo=undo,
        )

    @classmethod
    def failure(cls, message: str, *, llm: str = "") -> SkillResult:
        return cls(ok=False, message_for_user=message, message_for_llm=llm or message, data=None)

    def to_llm_payload(self) -> str:
        """Texto compacto que se devuelve al modelo como resultado del tool."""
        parts = [self.message_for_llm or ("ok" if self.ok else "error")]
        if self.data is not None:
            import json

            try:
                parts.append(json.dumps(self.data, ensure_ascii=False, default=str)[:4000])
            except (TypeError, ValueError):
                parts.append(str(self.data)[:2000])
        return "\n".join(parts)


class Skill(abc.ABC):
    """Base de todas las habilidades."""

    #: nombre estable y único; se usa en tool calls y en el audit log
    name: str = "skill"
    #: descripción para el LLM: qué hace y CUÁNDO usarla (clave para el routing)
    description: str = ""
    #: JSON Schema de los parámetros
    parameters: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}
    #: tier de riesgo declarado en código (ADR-0002)
    tier: RiskTier = RiskTier.T0
    #: plataformas donde existe; vacío = todas
    platforms: tuple[str, ...] = ()
    #: si registra una acción inversa
    undoable: bool = False
    #: timeout interno
    timeout_s: float = 20.0
    #: si necesita red (se desactiva en modo offline)
    requires_network: bool = False

    def __init__(self, ctx: SkillContext) -> None:
        self.ctx = ctx

    @abc.abstractmethod
    def execute(self, **kwargs: Any) -> SkillResult:
        """Implementación. Puede ser síncrona; el orquestador la pasa a thread si hace falta."""

    # -- utilidades ------------------------------------------------------- #
    @property
    def adapter(self) -> OSAdapter:
        return self.ctx.adapter

    @property
    def settings(self) -> Settings:
        return self.ctx.settings

    def to_tool_spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, parameters=self.parameters)

    def available_here(self) -> tuple[bool, str]:
        if self.platforms and not self.ctx.policy.supports_platform(set(self.platforms)):
            return False, f"skill {self.name} no disponible en esta plataforma"
        if self.requires_network and self.ctx.offline:
            return False, f"skill {self.name} requiere red y estás en modo offline"
        return True, ""


class SkillRegistry:
    """Catálogo de skills disponibles + validación de argumentos."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> Skill:
        if skill.name in self._skills:
            raise ValueError(f"skill duplicado: {skill.name}")
        self.validate_schema(skill)
        self._skills[skill.name] = skill
        return skill

    def register_many(self, skills: list[Skill]) -> None:
        for skill in skills:
            self.register(skill)

    @staticmethod
    def validate_schema(skill: Skill) -> None:
        """Falla en el registro (no en ejecución) si el esquema está mal escrito."""
        jsonschema.Draft202012Validator.check_schema(skill.parameters)
        if not skill.description.strip():
            raise ValueError(f"el skill {skill.name} necesita una descripción para el LLM")
        if skill.tier not in set(RiskTier):
            raise ValueError(f"tier inválido en {skill.name}")

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name) or self._skills.get(name.replace("_", "."))

    def names(self) -> set[str]:
        return set(self._skills)

    def all(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda s: s.name)

    def usable(self, *, offline: bool = False) -> list[Skill]:
        out = []
        for skill in self._skills.values():
            ok, _ = _availability(skill, offline)
            if ok:
                out.append(skill)
        return sorted(out, key=lambda s: s.name)

    def tool_specs(self, *, offline: bool = False) -> list[ToolSpec]:
        return [s.to_tool_spec() for s in self.usable(offline=offline)]

    def validate_arguments(self, name: str, arguments: dict[str, Any]) -> tuple[bool, str]:
        """Valida contra el JSON Schema. Se ejecuta ANTES del policy engine."""
        skill = self.get(name)
        if skill is None:
            return False, f"skill desconocido: {name}"
        try:
            jsonschema.validate(instance=arguments or {}, schema=skill.parameters)
            return True, ""
        except jsonschema.ValidationError as exc:
            path = ".".join(str(p) for p in exc.absolute_path) or "(raíz)"
            return False, f"argumentos inválidos en {path}: {exc.message}"

    def run(self, name: str, arguments: dict[str, Any]) -> SkillResult:
        """Ejecuta SIN pasar por política. Solo para `jarvis run` con validación propia."""
        skill = self.get(name)
        if skill is None:
            return SkillResult.failure(f"skill desconocido: {name}")
        started = time.perf_counter()
        try:
            result = skill.execute(**(arguments or {}))
        except TypeError as exc:
            result = SkillResult.failure(f"parámetros incorrectos: {exc}")
        except Exception as exc:
            result = SkillResult.failure(
                f"error interno del skill: {exc}", llm=f"{type(exc).__name__}: {exc}"
            )
        result.duration_ms = (time.perf_counter() - started) * 1000
        return result

    def describe_table(self) -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "tier": s.tier.value,
                "platforms": ",".join(s.platforms) or "todas",
                "undoable": "sí" if s.undoable else "no",
                "network": "sí" if s.requires_network else "no",
                "description": s.description.split(". ")[0],
            }
            for s in self.all()
        ]


def _availability(skill: Skill, offline: bool) -> tuple[bool, str]:
    from jarvis.platforms.factory import detect_platform

    current = detect_platform().value
    if skill.platforms and current not in {p.lower() for p in skill.platforms}:
        return False, "plataforma"
    if skill.requires_network and offline:
        return False, "offline"
    return True, ""
