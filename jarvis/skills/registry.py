"""Construcción del catálogo de skills por defecto."""

from __future__ import annotations

import logging

from jarvis.skills.apps import (
    CloseWindowSkill,
    FocusWindowSkill,
    LaunchAppSkill,
    ListAppsSkill,
    ListWindowsSkill,
)
from jarvis.skills.base import SkillContext, SkillRegistry
from jarvis.skills.desktop import (
    BrightnessSkill,
    ClipboardGetSkill,
    ClipboardSetSkill,
    NoteCreateSkill,
    NoteListSkill,
    NotifySkill,
    VolumeSkill,
)
from jarvis.skills.files import OpenFileSkill, ReadFileSkill, SearchFilesSkill
from jarvis.skills.shell import ShellRunSkill
from jarvis.skills.system_info import (
    BatterySkill,
    CapabilitiesSkill,
    DiskUsageSkill,
    ListenersSkill,
    ProcessesSkill,
    SystemInfoSkill,
    TemperatureSkill,
    TimeSkill,
    UpdateCheckSkill,
)
from jarvis.skills.web import OpenUrlSkill, WebSearchSkill

DEFAULT_SKILLS: tuple[type, ...] = (
    # T0 - lectura inocua
    TimeSkill,
    SystemInfoSkill,
    DiskUsageSkill,
    ProcessesSkill,
    BatterySkill,
    TemperatureSkill,
    ListenersSkill,
    UpdateCheckSkill,
    CapabilitiesSkill,
    ListAppsSkill,
    ListWindowsSkill,
    SearchFilesSkill,
    ReadFileSkill,
    NoteListSkill,
    ClipboardGetSkill,
    # T1 - escritura reversible
    LaunchAppSkill,
    FocusWindowSkill,
    VolumeSkill,
    BrightnessSkill,
    ClipboardSetSkill,
    NotifySkill,
    NoteCreateSkill,
    OpenFileSkill,
    # T2 - irreversible / red
    CloseWindowSkill,
    OpenUrlSkill,
    WebSearchSkill,
    # T3 - privilegiado
    ShellRunSkill,
)


def build_registry(ctx: SkillContext, *, extra_modules: tuple[str, ...] = ()) -> SkillRegistry:
    """Instancia y registra todos los skills. Falla rápido si un esquema está mal."""
    registry = SkillRegistry()
    registry.register_many([cls(ctx) for cls in DEFAULT_SKILLS])

    for module_name in extra_modules:
        _load_user_skills(module_name, ctx, registry)
    return registry


def _load_user_skills(module_name: str, ctx: SkillContext, registry: SkillRegistry) -> None:
    """Carga skills de terceros. Arrancan con tier mínimo T2 (docs/03 §4)."""
    import importlib

    from jarvis.safety.policy import RiskTier
    from jarvis.skills.base import Skill

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        logging.getLogger("jarvis.skills").warning("no se pudo cargar %s: %s", module_name, exc)
        return

    for attr in vars(module).values():
        if not (isinstance(attr, type) and issubclass(attr, Skill) and attr is not Skill):
            continue
        skill = attr(ctx)
        if skill.tier.rank < RiskTier.T2.rank:
            logging.getLogger("jarvis.skills").warning(
                "skill de terceros %s declaraba %s; se eleva a T2 por política",
                skill.name,
                skill.tier.value,
            )
            skill.tier = RiskTier.T2
        if skill.name in registry.names():
            logging.getLogger("jarvis.skills").warning("skill duplicado ignorado: %s", skill.name)
            continue
        ctx.bus.publish("skill.third_party_loaded", source="registry", name=skill.name, module=module_name)
        registry.register(skill)
