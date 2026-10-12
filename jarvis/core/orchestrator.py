"""Orquestador: el bucle del agente (docs/01 §3.1).

    percibir → enriquecer contexto → planificar (matcher N0 / LLM) → gobernar
    → ejecutar → reflexionar → responder → persistir

Es la pieza que une providers, skills, policy y memoria. No sabe de audio ni de
UI: recibe texto y devuelve texto + la lista de acciones realizadas.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Any

from jarvis.config.personas import ContextDigest, build_system_prompt
from jarvis.config.settings import Settings, get_settings
from jarvis.core._async import run_async
from jarvis.core.events import (
    AGENT_STEP,
    CONTEXT_ENRICHED,
    POLICY_DECISION,
    TOOL_PROPOSED,
    TOOL_RESULT,
    TURN_COMPLETED,
    get_bus,
)
from jarvis.core.matcher import match as match_canonical
from jarvis.core.memory import ConversationMemory
from jarvis.core.router import Router
from jarvis.platforms.base import OSAdapter
from jarvis.platforms.factory import get_adapter
from jarvis.providers.base import CompletionResult, Message
from jarvis.safety.audit import AuditLog
from jarvis.safety.policy import BudgetGuard, Decision, PolicyEngine, RiskTier, redact
from jarvis.skills.base import ApprovalHandler, AutoApprove, SkillContext, SkillRegistry, SkillResult
from jarvis.skills.registry import build_registry

log = logging.getLogger("jarvis.agent")


@dataclass(slots=True)
class ActionRecord:
    """Una acción propuesta y su desenlace. Se muestra en la UI y se audita."""

    skill: str
    arguments: dict[str, Any]
    tier: str
    decision: str
    reasons: list[str] = field(default_factory=list)
    ok: bool | None = None
    message: str = ""
    duration_ms: float = 0.0
    origin: str = "llm"  # llm | matcher | watchdog


@dataclass(slots=True)
class TurnResult:
    reply: str
    actions: list[ActionRecord] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    cost_usd: float = 0.0
    tokens: int = 0
    latency_ms: float = 0.0
    matched_locally: bool = False
    suggestions: list[str] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    def summary_line(self) -> str:
        bits = []
        if self.provider:
            bits.append(f"{self.provider}/{self.model}")
        elif self.matched_locally:
            bits.append("matcher-local")
        if self.actions:
            bits.append(f"{len(self.actions)} acción(es)")
        bits.append(f"{self.latency_ms:.0f} ms")
        if self.cost_usd:
            bits.append(f"{self.cost_usd:.5f} USD")
        return " · ".join(bits)


class Orchestrator:
    """Punto de entrada del agente. Una instancia por sesión."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        adapter: OSAdapter | None = None,
        approval: ApprovalHandler | None = None,
        router: Router | None = None,
        audit: AuditLog | None = None,
        offline: bool | None = None,
        extra_skill_modules: tuple[str, ...] = (),
    ) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_dirs()
        self.adapter = adapter or get_adapter()
        self.bus = get_bus()
        self.audit = audit or AuditLog(self.settings.audit_db)
        self.policy = PolicyEngine(self.settings)
        self.budget: BudgetGuard = self.policy.budget
        self.approval = approval or AutoApprove()
        self.offline = self.settings.effective_offline() if offline is None else offline
        self.router = router or Router(self.settings, budget=self.budget)
        self.memory = ConversationMemory(self.settings)
        self.turn_count = 0
        self._last_undo: tuple[str, Any] | None = None

        self.ctx = SkillContext(
            settings=self.settings,
            adapter=self.adapter,
            policy=self.policy,
            audit=self.audit,
            bus=self.bus,
            approval=self.approval,
            offline=self.offline,
        )
        self.registry: SkillRegistry = build_registry(self.ctx, extra_modules=extra_skill_modules)
        self._context_cache: tuple[float, ContextDigest] | None = None

    # ------------------------------------------------------------------ #
    # Contexto
    # ------------------------------------------------------------------ #
    def context_digest(self, *, max_age_s: float = 4.0) -> ContextDigest:
        """Contexto del sistema cacheado: llamarlo en cada turno no debe costar I/O."""
        now = time.time()
        if self._context_cache and now - self._context_cache[0] < max_age_s:
            return self._context_cache[1]
        digest = ContextDigest.capture()
        extra: dict[str, str] = {}
        try:
            info = self.adapter.system_info()
            if info.memory:
                extra["RAM usada"] = f"{info.memory.used_pct}%"
            disks = self.adapter.disks()
            if disks:
                extra["Disco (mayor uso)"] = f"{disks[0].mount} al {disks[0].used_pct}%"
            window = self.adapter.active_window()
            if window and window.title:
                extra["Ventana activa"] = window.title[:80]
        except Exception as exc:
            log.debug("contexto incompleto: %s", exc)
        extra["Modo"] = "offline" if self.offline else "online"
        digest = replace(digest, extra=extra)
        self._context_cache = (now, digest)
        self.bus.publish(CONTEXT_ENRICHED, source="agent", **{k: str(v)[:80] for k, v in extra.items()})
        return digest

    def system_prompt(self) -> str:
        return build_system_prompt(self.settings, self.context_digest())

    # ------------------------------------------------------------------ #
    # Turno completo
    # ------------------------------------------------------------------ #
    def handle(self, user_text: str, *, profile: str | None = None) -> TurnResult:
        """Procesa una entrada de texto (de la CLI, del STT o de la API)."""
        started = time.perf_counter()
        self.turn_count += 1
        turn_id = f"t{self.turn_count}-{uuid.uuid4().hex[:6]}"
        self.ctx.turn_id = turn_id
        text = user_text.strip()
        if not text:
            return TurnResult(reply="", error="entrada vacía", latency_ms=0.0)

        self.audit.record("turn.started", turn_id=turn_id, chars=len(text))

        # Redacción de secretos antes de que el texto salga del proceso.
        if self.settings.privacy.redact_secrets and not self.offline:
            text, hits = redact(text)
            if hits:
                log.warning("se enmascararon %d posibles secretos en la entrada del usuario", hits)

        # N0: matcher determinista (0 tokens).
        local = match_canonical(text, min_confidence=self.settings.router.local_matcher_min_confidence)
        if local is not None and self.settings.router.local_matcher_enabled:
            record = self._execute_proposed(
                local.skill, local.arguments, origin="matcher", tier_hint=local.tier_hint
            )
            reply = self._reply_for_local(record)
            result = TurnResult(
                reply=reply,
                actions=[record],
                matched_locally=True,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
            self.memory.add("user", user_text)
            self.memory.add("assistant", reply, meta={"matched": local.rule})
            self._finish(result, turn_id, started)
            return result

        # N1/N2: LLM con tool calling.
        self.memory.add("user", text)
        return self._agent_loop(text, profile=profile, turn_id=turn_id, started=started)

    def _agent_loop(self, text: str, *, profile: str | None, turn_id: str, started: float) -> TurnResult:
        actions: list[ActionRecord] = []
        messages = self.memory.history(system=self.system_prompt())
        tools = self.registry.tool_specs(offline=self.offline)
        cost = 0.0
        tokens = 0
        provider_used = model_used = ""
        last_text = ""
        max_steps = self.settings.router.max_steps_per_turn

        for step in range(max_steps):
            self.bus.publish(AGENT_STEP, source="agent", step=step + 1, turn_id=turn_id)
            route = run_async(
                self.router.complete(
                    messages=messages, tools=tools, profile=profile or ("cheap" if step == 0 else None)
                )
            )
            if not route.ok or route.result is None:
                error = route.explain()
                self.audit.record("turn.llm_failed", turn_id=turn_id, error=error)
                if actions:
                    return TurnResult(
                        reply=_render_actions(actions) + f"\n\n(No pude generar el resumen: {error})",
                        actions=actions,
                        matched_locally=False,
                        latency_ms=(time.perf_counter() - started) * 1000,
                        error=error,
                    )
                return TurnResult(
                    reply=_offline_fallback(self, text),
                    actions=actions,
                    error=error,
                    latency_ms=(time.perf_counter() - started) * 1000,
                )

            result: CompletionResult = route.result
            provider_used, model_used = route.provider_used, route.model_used
            cost += result.cost_usd
            tokens += result.usage.total
            last_text = result.text.strip()

            if not result.wants_tool:
                break

            # El modelo pidió herramientas: gobernar y ejecutar cada una.
            messages.append(Message(role="assistant", content=result.text, tool_calls=result.tool_calls))
            for call in result.tool_calls:
                record = self._execute_proposed(call.skill, call.arguments, origin="llm")
                actions.append(record)
                messages.append(
                    Message(
                        role="tool",
                        content=record.message,
                        name=call.skill,
                        tool_call_id=call.id,
                    )
                )
            if len(result.tool_calls) == 0:
                break
        else:
            log.warning("turno %s alcanzó el tope de %d pasos", turn_id, max_steps)
            last_text = (last_text + " (se alcanzó el tope de pasos del turno)").strip()

        reply = last_text or _render_actions(actions) or "Hecho."
        if actions and reply and not any(a.message in reply for a in actions if a.ok):
            reply = reply.strip()
        self.memory.add("assistant", reply, meta={"provider": provider_used, "model": model_used})
        self.memory.add_cost(cost)

        turn = TurnResult(
            reply=reply,
            actions=actions,
            provider=provider_used,
            model=model_used,
            cost_usd=round(cost, 6),
            tokens=tokens,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        self._finish(turn, turn_id, started)
        return turn

    def _finish(self, result: TurnResult, turn_id: str, started: float) -> None:
        result.latency_ms = (time.perf_counter() - started) * 1000
        self.audit.record(
            "turn.completed",
            turn_id=turn_id,
            actions=len(result.actions),
            matched=result.matched_locally,
            provider=result.provider,
            model=result.model,
            cost_usd=result.cost_usd,
            tokens=result.tokens,
            latency_ms=round(result.latency_ms, 1),
            error=result.error,
        )
        self.bus.publish(
            TURN_COMPLETED,
            source="agent",
            turn_id=turn_id,
            actions=len(result.actions),
            cost_usd=result.cost_usd,
            ms=round(result.latency_ms, 1),
            matched=result.matched_locally,
            provider=result.provider,
        )
        result.suggestions = self._suggest_after_turn(result)

    # ------------------------------------------------------------------ #
    # Gobernanza + ejecución de una propuesta
    # ------------------------------------------------------------------ #
    def _execute_proposed(
        self,
        skill_name: str,
        arguments: dict[str, Any],
        *,
        origin: str = "llm",
        tier_hint: RiskTier | None = None,
    ) -> ActionRecord:
        self.bus.publish(TOOL_PROPOSED, source=origin, skill=skill_name, args=_safe_args(arguments))
        skill = self.registry.get(skill_name)
        if skill is None:
            self.audit.record("tool.unknown", skill=skill_name, origin=origin, args=_safe_args(arguments))
            return ActionRecord(
                skill=skill_name,
                arguments=arguments,
                tier="?",
                decision="deny",
                reasons=[f"skill desconocido: {skill_name}"],
                ok=False,
                message=(
                    f"skill desconocido: no existe ninguna habilidad llamada '{skill_name}'. "
                    f"Disponibles: {', '.join(sorted(self.registry.names())[:12])}…"
                ),
                origin=origin,
            )

        # 1) validación de esquema
        schema_ok, schema_error = self.registry.validate_arguments(skill_name, arguments)
        if not schema_ok:
            self.audit.record(
                "tool.schema_invalid",
                skill=skill_name,
                tier=skill.tier.value,
                decision="deny",
                reason=schema_error,
                args=_safe_args(arguments),
            )
            return ActionRecord(
                skill=skill_name,
                arguments=arguments,
                tier=skill.tier.value,
                decision="deny",
                reasons=[schema_error],
                ok=False,
                message=f"No puedo ejecutar {skill_name}: {schema_error}",
                origin=origin,
            )

        # 2) política. El tier SIEMPRE sale de la clase del skill (ADR-0002):
        #    `tier_hint` solo puede elevarlo, nunca reducirlo.
        base_tier = skill.tier
        if tier_hint is not None and tier_hint.rank > base_tier.rank:
            base_tier = tier_hint
        verdict = self.policy.evaluate(
            skill_name,
            arguments,
            base_tier,
            skill_exists=True,
            platforms=set(skill.platforms),
            undoable=skill.undoable,
            known_skills=self.registry.names(),
        )
        self.bus.publish(
            POLICY_DECISION,
            source="policy",
            skill=skill_name,
            decision=verdict.decision.value,
            tier=verdict.tier.value,
            reasons=verdict.reasons[:3],
        )
        self.audit.record(
            "policy.decision",
            skill=skill_name,
            tier=verdict.tier.value,
            decision=verdict.decision.value,
            reasons=verdict.reasons,
            args=_safe_args(arguments),
            origin=origin,
        )

        if verdict.decision is Decision.DENY:
            return ActionRecord(
                skill=skill_name,
                arguments=arguments,
                tier=verdict.tier.value,
                decision="deny",
                reasons=verdict.reasons,
                ok=False,
                message=f"Denegado por política: {'; '.join(verdict.reasons)}",
                origin=origin,
            )

        # 3) disponibilidad en esta plataforma / modo offline
        available, why = skill.available_here()
        if not available:
            return ActionRecord(
                skill=skill_name,
                arguments=arguments,
                tier=verdict.tier.value,
                decision="deny",
                reasons=[why],
                ok=False,
                message=why,
                origin=origin,
            )

        # 4) aprobación humana si hace falta
        if verdict.decision is Decision.REQUIRE_APPROVAL:
            granted = self.approval.request(
                skill=skill_name,
                arguments=arguments,
                tier=verdict.tier,
                reasons=verdict.reasons,
                typed_confirmation=verdict.requires_typed_confirmation,
                timeout_s=self.settings.policy.approval_timeout_s,
            )
            self.bus.publish(
                "approval.granted" if granted else "approval.denied",
                source="policy",
                skill=skill_name,
                tier=verdict.tier.value,
            )
            self.audit.record(
                "approval",
                skill=skill_name,
                tier=verdict.tier.value,
                decision="granted" if granted else "denied",
                args=_safe_args(arguments),
            )
            if not granted:
                return ActionRecord(
                    skill=skill_name,
                    arguments=arguments,
                    tier=verdict.tier.value,
                    decision="require_approval",
                    reasons=verdict.reasons,
                    ok=False,
                    message=f"Acción cancelada por el usuario ({skill_name}).",
                    origin=origin,
                )

        # 5) ejecución
        started = time.perf_counter()
        result: SkillResult = self.registry.run(skill_name, arguments)
        result.duration_ms = (time.perf_counter() - started) * 1000
        self.budget.record_action()
        if result.undo is not None:
            self._last_undo = (skill_name, result.undo)
        self.bus.publish(
            TOOL_RESULT,
            source=skill_name,
            ok=result.ok,
            ms=round(result.duration_ms, 1),
            skill=skill_name,
        )
        self.audit.record(
            "tool.executed" if result.ok else "tool.failed",
            skill=skill_name,
            tier=verdict.tier.value,
            decision=verdict.decision.value,
            ms=round(result.duration_ms, 1),
            message=result.message_for_user[:500],
            args=_safe_args(arguments),
        )
        return ActionRecord(
            skill=skill_name,
            arguments=arguments,
            tier=verdict.tier.value,
            decision=verdict.decision.value,
            reasons=verdict.reasons,
            ok=result.ok,
            message=result.message_for_user or ("ok" if result.ok else "error"),
            duration_ms=result.duration_ms,
            origin=origin,
        )

    def run_skill(
        self, name: str, arguments: dict[str, Any] | None = None, *, yes: bool = False
    ) -> ActionRecord:
        """Ejecución directa desde la CLI (`jarvis run`). Pasa por la misma política."""
        if yes:
            self.approval = _YesApproval()
        return self._execute_proposed(name, arguments or {}, origin="cli")

    def undo_last(self) -> str:
        if self._last_undo is None:
            return "No hay ninguna acción reversible reciente."
        name, undo = self._last_undo
        self._last_undo = None
        result = undo()
        self.audit.record("tool.undo", skill=name, decision="ok" if result.ok else "failed")
        return result.message_for_user

    # ------------------------------------------------------------------ #
    # Sugerencias post-turno (semilla de la proactividad, Fase 4)
    # ------------------------------------------------------------------ #
    def _suggest_after_turn(self, result: TurnResult) -> list[str]:
        suggestions: list[str] = []
        try:
            for volume in self.adapter.disks()[:1]:
                if volume.used_pct >= self.settings.watchdog.disk_crit_pct:
                    suggestions.append(
                        f"El volumen {volume.mount} está al {volume.used_pct}%. "
                        "Pídeme 'limpia caches' y te propongo qué borrar (siempre con confirmación)."
                    )
                elif volume.used_pct >= self.settings.watchdog.disk_warn_pct:
                    suggestions.append(
                        f"El volumen {volume.mount} va por el {volume.used_pct}%. Conviene ir haciendo hueco."
                    )
            info = self.adapter.system_info()
            if info.memory and info.memory.used_pct >= self.settings.watchdog.ram_crit_pct:
                suggestions.append(
                    f"RAM al {info.memory.used_pct}%. ¿Quieres que liste los procesos que más consumen?"
                )
        except Exception as exc:
            log.debug("sugerencias post-turno omitidas: %s", exc)

        denied = [a for a in result.actions if a.decision == "deny"]
        if denied:
            suggestions.append(
                "Se denegó una acción por política. Revisa `jarvis audit --tail` para ver el motivo exacto."
            )
        return suggestions

    def _reply_for_local(self, record: ActionRecord) -> str:
        """Respuesta para las órdenes resueltas por el matcher (sin LLM)."""
        return record.message

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        """Cierra memoria y auditoría sin propagar errores de cierre (best effort)."""
        with contextlib.suppress(Exception):
            self.memory.close()
        with contextlib.suppress(Exception):
            self.audit.close()


class _YesApproval(ApprovalHandler):
    """Aprueba todo. Solo se activa con `--yes` explícito en la CLI (y se audita)."""

    def request(self, **kwargs: Any) -> bool:
        return True


def _safe_args(arguments: dict[str, Any]) -> dict[str, Any]:
    """Recorta y redacta los argumentos antes de loggearlos o auditarlos."""
    out: dict[str, Any] = {}
    for key, value in (arguments or {}).items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        text, _hits = redact(text[:600])
        out[key] = text
    return out


def _render_actions(actions: list[ActionRecord]) -> str:
    lines = []
    for action in actions:
        icon = "✅" if action.ok else "⛔" if action.decision == "deny" else "⚠️"
        lines.append(f"{icon} {action.skill} [{action.tier}] → {action.message}")
    return "\n".join(lines)


def _offline_fallback(orch: Orchestrator, text: str) -> str:
    """Mensaje útil cuando ningún proveedor está disponible."""
    chain = orch.settings.router.default_chain
    return (
        "No pude contactar con ningún modelo de IA y el matcher local no reconoció la orden.\n"
        f"Cadena configurada: {', '.join(chain)}.\n"
        "Comprueba las claves con `jarvis doctor --providers`, o arranca Ollama para el modo local.\n"
        f"Mientras tanto puedo ejecutar órdenes directas: escribe `jarvis skills` para verlas.\n"
        f"(Tu petición fue: “{text[:120]}”)"
    )
