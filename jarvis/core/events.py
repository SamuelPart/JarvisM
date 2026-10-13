"""Event bus interno.

Todo lo interesante que ocurre en JarvisM se publica aquí. La TUI, el HUD, el
servidor web y los tests son consumidores del mismo flujo (ver docs/01 §3).

Es síncrono a propósito: publicar un evento debe costar microsegundos y no puede
bloquearse esperando a un consumidor lento. Los handlers que hagan I/O deben
lanzar su propia tarea.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("jarvis.events")

Handler = Callable[["Event"], None]


@dataclass(slots=True)
class Event:
    name: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    source: str = "core"

    def __str__(self) -> str:  # pragma: no cover - solo para logs
        return f"{self.name} {self.data}"


# Nombres canónicos. Usar constantes evita typos silenciosos.
WAKE_DETECTED = "wake.detected"
STT_TRANSCRIPT = "stt.transcript"
CONTEXT_ENRICHED = "context.enriched"
LLM_REQUEST = "llm.request"
LLM_RESPONSE = "llm.response"
TOOL_PROPOSED = "tool.proposed"
POLICY_DECISION = "policy.decision"
APPROVAL_REQUESTED = "approval.requested"
APPROVAL_GRANTED = "approval.granted"
APPROVAL_DENIED = "approval.denied"
TOOL_RESULT = "tool.result"
AGENT_STEP = "agent.step"
TURN_COMPLETED = "turn.completed"
SUGGESTION_EMITTED = "suggestion.emitted"
SUGGESTION_FEEDBACK = "suggestion.feedback"
BUDGET_THRESHOLD = "budget.threshold"
WATCHDOG_ALERT = "watchdog.alert"
PROVIDER_FAILOVER = "provider.failover"


class EventBus:
    """Suscripción por nombre exacto o por prefijo (`llm.*`)."""

    def __init__(self, history_size: int = 500) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._history: deque[Event] = deque(maxlen=history_size)

    def subscribe(self, pattern: str, handler: Handler) -> Callable[[], None]:
        self._handlers[pattern].append(handler)

        def unsubscribe() -> None:
            if handler in self._handlers[pattern]:
                self._handlers[pattern].remove(handler)

        return unsubscribe

    def publish(self, name: str, /, source: str = "core", **data: Any) -> Event:
        event = Event(name=name, data=data, source=source)
        self._history.append(event)
        for pattern, handlers in self._handlers.items():
            if (
                pattern == name
                or (pattern.endswith(".*") and name.startswith(pattern[:-1]))
                or pattern == "*"
            ):
                for handler in handlers:
                    try:
                        handler(event)
                    except Exception:
                        log.exception("handler de %s falló", pattern)
        return event

    def history(self, prefix: str | None = None, limit: int = 100) -> list[Event]:
        events = list(self._history)
        if prefix:
            events = [e for e in events if e.name.startswith(prefix)]
        return events[-limit:]

    def reset(self) -> None:
        self._history.clear()


_bus: EventBus | None = None


def get_bus() -> EventBus:
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
