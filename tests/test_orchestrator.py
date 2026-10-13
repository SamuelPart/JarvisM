"""Tests de integración del bucle del agente, con adapter y proveedor falsos."""

from __future__ import annotations

from jarvis.core.orchestrator import Orchestrator
from jarvis.core.router import Router
from jarvis.providers.base import CompletionResult, ToolCall, Usage
from jarvis.providers.registry import ProviderRegistry
from jarvis.safety.policy import Decision
from tests.conftest import Approvals, ScriptedProvider


def build_orchestrator(settings, fake_adapter, audit, responses, *, approval=None, offline=False):
    """Orquestador con cadena de un solo proveedor simulado."""
    registry = ProviderRegistry(settings=settings)
    provider = ScriptedProvider(responses)
    registry._providers = {"scripted": provider}
    settings.router.default_chain = ["scripted"]
    router = Router(settings, registry=registry)
    orch = Orchestrator(
        settings,
        adapter=fake_adapter,
        approval=approval or Approvals(),
        router=router,
        audit=audit,
        offline=offline,
    )
    orch.provider = provider  # type: ignore[attr-defined]
    return orch


# --------------------------------------------------------------------------- #
# Turnos resueltos sin LLM (N0)
# --------------------------------------------------------------------------- #
def test_canonical_order_uses_matcher_and_no_tokens(settings, fake_adapter, audit) -> None:
    orch = build_orchestrator(settings, fake_adapter, audit, responses=[])
    result = orch.handle("¿qué hora es?")
    assert result.matched_locally
    assert result.cost_usd == 0.0
    assert result.tokens == 0
    assert "Son las" in result.reply
    assert len(orch.provider.requests) == 0  # type: ignore[attr-defined]
    orch.close()


def test_matcher_launches_app_and_registers_undo(settings, fake_adapter, audit) -> None:
    orch = build_orchestrator(settings, fake_adapter, audit, responses=[])
    result = orch.handle("abre firefox")
    assert result.matched_locally
    assert fake_adapter.launched
    assert "firefox" in result.reply.lower() or "Firefox" in result.reply
    orch.close()


# --------------------------------------------------------------------------- #
# Turnos con LLM
# --------------------------------------------------------------------------- #
def test_llm_plain_answer(settings, fake_adapter, audit) -> None:
    orch = build_orchestrator(
        settings,
        fake_adapter,
        audit,
        responses=[CompletionResult(text="La respuesta es 42.", usage=Usage(100, 20))],
    )
    result = orch.handle("dime la respuesta a todo")
    assert result.reply == "La respuesta es 42."
    assert result.provider == "scripted"
    assert result.tokens == 120
    assert not result.matched_locally
    orch.close()


def test_llm_tool_call_is_executed_and_fed_back(settings, fake_adapter, audit) -> None:
    orch = build_orchestrator(
        settings,
        fake_adapter,
        audit,
        responses=[
            CompletionResult(
                text="",
                tool_calls=[ToolCall(id="c1", skill="system.disk", arguments={})],
                usage=Usage(80, 10),
            ),
            CompletionResult(text="Tienes disco de sobra.", usage=Usage(120, 15)),
        ],
    )
    result = orch.handle("cómo va el disco de este equipo")
    assert len(orch.provider.requests) == 2  # type: ignore[attr-defined]
    assert result.actions[0].skill == "system.disk"
    assert result.actions[0].ok
    assert "disco de sobra" in result.reply
    # El resultado de la herramienta debe viajar de vuelta al modelo.
    last_messages = orch.provider.requests[-1].messages  # type: ignore[attr-defined]
    assert any(m.role == "tool" for m in last_messages)
    orch.close()


def test_llm_tool_call_requiring_approval_is_denied(settings, fake_adapter, audit) -> None:
    approvals = Approvals(grant=False)
    orch = build_orchestrator(
        settings,
        fake_adapter,
        audit,
        approval=approvals,
        responses=[
            CompletionResult(
                text="",
                tool_calls=[ToolCall(id="c1", skill="web.open", arguments={"target": "example.com"})],
            ),
            CompletionResult(text="No abro nada entonces."),
        ],
    )
    result = orch.handle("abre la web esa rara")
    assert approvals.seen, "debía pedirse aprobación para T2"
    assert result.actions[0].decision == "require_approval"
    assert not result.actions[0].ok
    assert "cancelada" in result.actions[0].message.lower()
    orch.close()


def test_llm_invented_skill_is_rejected(settings, fake_adapter, audit) -> None:
    orch = build_orchestrator(
        settings,
        fake_adapter,
        audit,
        responses=[
            CompletionResult(
                text="", tool_calls=[ToolCall(id="c1", skill="system.format_disk", arguments={})]
            ),
            CompletionResult(text="No tengo esa capacidad."),
        ],
    )
    result = orch.handle("formatea el disco")
    assert result.actions[0].decision == "deny"
    assert "desconocido" in result.actions[0].message or "no registrado" in result.actions[0].message
    orch.close()


def test_llm_tool_call_with_invalid_arguments_is_rejected(settings, fake_adapter, audit) -> None:
    orch = build_orchestrator(
        settings,
        fake_adapter,
        audit,
        responses=[
            CompletionResult(text="", tool_calls=[ToolCall(id="c1", skill="apps.launch", arguments={})]),
            CompletionResult(text="Necesito el nombre de la app."),
        ],
    )
    result = orch.handle("abre lo que sea")
    assert not result.actions[0].ok
    assert "inválidos" in result.actions[0].message
    assert not fake_adapter.launched
    orch.close()


def test_dangerous_shell_call_through_llm_is_denied(settings, fake_adapter, audit) -> None:
    """El modelo pide lo más peligroso posible: el sistema debe negarse."""
    orch = build_orchestrator(
        settings,
        fake_adapter,
        audit,
        responses=[
            CompletionResult(
                text="",
                tool_calls=[
                    ToolCall(
                        id="c1", skill="shell.run", arguments={"command": "rm -rf /", "reason": "limpiar"}
                    )
                ],
            ),
            CompletionResult(text="No puedo hacer eso."),
        ],
    )
    result = orch.handle("limpia el sistema a fondo")
    assert result.actions[0].decision == "deny"
    assert "prohibido" in result.actions[0].message
    orch.close()


def test_unknown_cmdlet_proposal_tier_cannot_override(settings, fake_adapter, audit) -> None:
    """Auditoría del invariante: shell.run es T3 siempre, no importa cómo se invoque."""
    orch = build_orchestrator(settings, fake_adapter, audit, responses=[])
    record = orch._execute_proposed(
        "shell.run", {"command": "ls", "reason": "listar el directorio actual"}, origin="llm"
    )
    assert record.tier == "T3"
    assert record.decision == Decision.REQUIRE_APPROVAL.value
    orch.close()


def test_all_providers_fail_returns_useful_message(settings, fake_adapter, audit) -> None:
    registry = ProviderRegistry(settings=settings)
    registry._providers = {}
    settings.router.default_chain = []
    router = Router(settings, registry=registry)
    orch = Orchestrator(
        settings, adapter=fake_adapter, approval=Approvals(), router=router, audit=audit, offline=False
    )
    result = orch.handle("explícame algo profundo sobre la vida")
    assert result.error
    assert "No pude contactar" in result.reply
    assert "jarvis skills" in result.reply
    orch.close()


# --------------------------------------------------------------------------- #
# Memoria y estado
# --------------------------------------------------------------------------- #
def test_conversation_memory_keeps_history(settings, fake_adapter, audit) -> None:
    orch = build_orchestrator(
        settings,
        fake_adapter,
        audit,
        responses=[CompletionResult(text="Uno."), CompletionResult(text="Dos.")],
    )
    orch.handle("primera pregunta abierta")
    orch.handle("segunda pregunta abierta")
    roles = [m.role for m in orch.memory.messages]
    assert roles == ["user", "assistant", "user", "assistant"]
    orch.close()


def test_offline_mode_skips_network_skills(settings, fake_adapter, audit) -> None:
    orch = build_orchestrator(settings, fake_adapter, audit, responses=[], offline=True)
    usable = {s.name for s in orch.registry.usable(offline=True)}
    assert "web.open" not in usable
    assert "system.info" in usable
    orch.close()


def test_kill_switch_blocks_actions(settings, fake_adapter, audit) -> None:
    orch = build_orchestrator(settings, fake_adapter, audit, responses=[])
    orch.policy.set_kill_switch(True)
    record = orch._execute_proposed("system.info", {}, origin="cli")
    assert record.decision == "deny"
    assert not fake_adapter.launched
    orch.close()


def test_undo_restores_previous_state(settings, fake_adapter, audit) -> None:
    fake_adapter.clipboard = "original"
    orch = build_orchestrator(settings, fake_adapter, audit, responses=[])
    orch._execute_proposed("clipboard.set", {"text": "nuevo"}, origin="cli")
    assert fake_adapter.clipboard == "nuevo"
    message = orch.undo_last()
    assert fake_adapter.clipboard == "original"
    assert "portapapeles" in message.lower()
    orch.close()


def test_audit_records_policy_decisions(settings, fake_adapter, audit) -> None:
    orch = build_orchestrator(settings, fake_adapter, audit, responses=[])
    orch._execute_proposed("system.disk", {}, origin="cli")
    kinds = {e.kind for e in audit.tail(20)}
    assert "policy.decision" in kinds
    assert "tool.executed" in kinds
    orch.close()


def test_suggestions_after_turn_when_disk_critical(settings, fake_adapter, audit) -> None:
    fake_adapter.disk_used_pct = 96.0
    orch = build_orchestrator(settings, fake_adapter, audit, responses=[])
    result = orch.handle("¿qué hora es?")
    assert result.suggestions
    assert any("96" in s for s in result.suggestions)
    orch.close()


def test_turn_is_recorded_in_audit(settings, fake_adapter, audit) -> None:
    orch = build_orchestrator(settings, fake_adapter, audit, responses=[CompletionResult(text="ok")])
    orch.handle("una pregunta abierta cualquiera")
    kinds = {e.kind for e in audit.tail(25)}
    assert "turn.started" in kinds
    assert "turn.completed" in kinds
    orch.close()


def test_system_prompt_includes_security_rules(settings, fake_adapter, audit) -> None:
    orch = build_orchestrator(settings, fake_adapter, audit, responses=[])
    prompt = orch.system_prompt()
    assert "REGLAS NO NEGOCIABLES" in prompt
    assert "DATOS_NO_INSTRUCCIONES" in prompt
    assert "Jarvis" in prompt
    orch.close()
