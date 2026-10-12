"""Núcleo del agente: orquestador, router, memoria, matcher y bus de eventos.

Las reexportaciones son **perezosas** (PEP 562) por una razón concreta: los skills
importan `jarvis.core.events`, y el orquestador importa los skills. Si este
`__init__` cargase el orquestador de forma eager, se produciría un ciclo de
importación al cargar `jarvis.skills`. Con import perezoso, `import
jarvis.core.events` no arrastra el orquestador y el ciclo desaparece.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - solo para type checkers
    from jarvis.core.events import EventBus
    from jarvis.core.matcher import Match
    from jarvis.core.memory import ConversationMemory
    from jarvis.core.orchestrator import ActionRecord, Orchestrator, TurnResult
    from jarvis.core.router import Router, RouteResult

__all__ = [
    "ActionRecord",
    "ConversationMemory",
    "EventBus",
    "Match",
    "Orchestrator",
    "RouteResult",
    "Router",
    "TurnResult",
    "coverage_report",
    "get_bus",
    "match",
    "memory_stats",
]

_LAZY: dict[str, tuple[str, str]] = {
    "EventBus": ("jarvis.core.events", "EventBus"),
    "get_bus": ("jarvis.core.events", "get_bus"),
    "Match": ("jarvis.core.matcher", "Match"),
    "match": ("jarvis.core.matcher", "match"),
    "coverage_report": ("jarvis.core.matcher", "coverage_report"),
    "ConversationMemory": ("jarvis.core.memory", "ConversationMemory"),
    "memory_stats": ("jarvis.core.memory", "memory_stats"),
    "ActionRecord": ("jarvis.core.orchestrator", "ActionRecord"),
    "Orchestrator": ("jarvis.core.orchestrator", "Orchestrator"),
    "TurnResult": ("jarvis.core.orchestrator", "TurnResult"),
    "Router": ("jarvis.core.router", "Router"),
    "RouteResult": ("jarvis.core.router", "RouteResult"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY.get(name)
    if target is None:
        raise AttributeError(f"module 'jarvis.core' has no attribute {name!r}")
    import importlib

    module = importlib.import_module(target[0])
    return getattr(module, target[1])


def __dir__() -> list[str]:
    return sorted(__all__)
