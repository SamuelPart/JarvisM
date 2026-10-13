"""Catálogo de habilidades (skills) de JarvisM."""

from jarvis.skills.base import (
    ApprovalHandler,
    AutoApprove,
    Skill,
    SkillContext,
    SkillRegistry,
    SkillResult,
)
from jarvis.skills.registry import DEFAULT_SKILLS, build_registry

__all__ = [
    "DEFAULT_SKILLS",
    "ApprovalHandler",
    "AutoApprove",
    "Skill",
    "SkillContext",
    "SkillRegistry",
    "SkillResult",
    "build_registry",
]
