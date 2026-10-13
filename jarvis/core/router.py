"""Router multi-proveedor: prioridad, salud, reintentos, failover y contabilidad.

Implementa la cascada de ADR-0003 en su nivel N1/N2. El nivel N0 (matcher local)
vive en `jarvis/core/matcher.py` y lo aplica el orquestador antes de llegar aquí.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

from jarvis.config.settings import Settings
from jarvis.core.events import (
    LLM_REQUEST,
    LLM_RESPONSE,
    PROVIDER_FAILOVER,
    get_bus,
)
from jarvis.providers.base import (
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    ProviderError,
    ProviderErrorKind,
    ToolSpec,
)
from jarvis.providers.registry import ProviderRegistry
from jarvis.safety.policy import BudgetGuard

log = logging.getLogger("jarvis.router")

#: Errores por los que merece la pena reintentar en el MISMO proveedor.
RETRYABLE = {
    ProviderErrorKind.RATE_LIMIT,
    ProviderErrorKind.SERVER,
    ProviderErrorKind.TIMEOUT,
    ProviderErrorKind.NETWORK,
}
#: Errores que hacen saltar directamente al siguiente proveedor.
FATAL_FOR_PROVIDER = {ProviderErrorKind.AUTH, ProviderErrorKind.NO_KEY, ProviderErrorKind.MODEL_NOT_FOUND}


@dataclass(slots=True)
class RouteAttempt:
    provider: str
    model: str
    ok: bool
    error: str = ""
    latency_ms: float = 0.0


@dataclass(slots=True)
class RouteResult:
    result: CompletionResult | None
    attempts: list[RouteAttempt] = field(default_factory=list)
    provider_used: str = ""
    model_used: str = ""
    total_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.result is not None

    def explain(self) -> str:
        if self.ok:
            return f"{self.provider_used}/{self.model_used} en {self.total_ms:.0f} ms"
        detail = "; ".join(f"{a.provider}: {a.error}" for a in self.attempts) or "sin proveedores"
        return f"todos los proveedores fallaron → {detail}"


class Router:
    """Elige proveedor y modelo, reintenta y conmuta."""

    def __init__(
        self,
        settings: Settings,
        registry: ProviderRegistry | None = None,
        budget: BudgetGuard | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry or ProviderRegistry.from_settings(settings)
        self.budget = budget or BudgetGuard(settings)
        self.bus = get_bus()
        self._rpm_window: list[float] = []
        self.stats: dict[str, dict[str, Any]] = {}

    # -- selección de modelo --------------------------------------------- #
    def model_for(self, profile: str | None = None) -> tuple[str, str]:
        """Devuelve (provider, model) para un perfil lógico.

        Los perfiles son estables; los nombres concretos de modelo viven en config,
        así que un rename del proveedor es un cambio de TOML, no de código (P10).
        """
        router_cfg = self.settings.router
        profile = (profile or router_cfg.profile or "general").lower()
        offline = self.settings.effective_offline()
        if offline or profile == "offline":
            return "ollama", router_cfg.model_offline
        mapping = {
            "cheap": router_cfg.model_cheap,
            "general": router_cfg.model_general,
            "reasoner": router_cfg.model_reasoner,
            "vision": router_cfg.model_vision,
        }
        model = mapping.get(profile, router_cfg.model_general)
        # El proveedor se deduce del prefijo del modelo si es reconocible; si no,
        # se deja que la cadena de failover decida.
        guessed = _guess_provider(model)
        return (guessed or (router_cfg.default_chain[0] if router_cfg.default_chain else "echo"), model)

    # -- rate limit ------------------------------------------------------- #
    async def _throttle(self) -> None:
        max_rpm = self.settings.router.max_rpm
        if max_rpm <= 0:
            return
        cutoff = time.time() - 60
        self._rpm_window = [t for t in self._rpm_window if t >= cutoff]
        if len(self._rpm_window) >= max_rpm:
            wait = 60 - (time.time() - self._rpm_window[0]) + random.uniform(0.1, 0.6)
            if wait > 0:
                log.info("rate limit local: esperando %.1f s", wait)
                await asyncio.sleep(min(wait, 60))
        self._rpm_window.append(time.time())

    # -- llamada principal ------------------------------------------------ #
    async def complete(
        self,
        *,
        messages: list[Any],
        tools: list[ToolSpec] | None = None,
        profile: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 1024,
        fallback_chain: list[str] | None = None,
    ) -> RouteResult:
        started = time.perf_counter()
        tool_list: list[ToolSpec] = list(tools or [])
        preferred_provider, preferred_model = self.model_for(profile)
        provider = provider or preferred_provider
        model = model or preferred_model
        offline = bool(self.settings.privacy.offline)

        # `offline` aquí significa "corta toda salida a la nube" (privacidad.offline);
        # la ausencia de claves no vacía la cadena: cada proveedor decide en available().
        chain = self.registry.chain(strict_offline=offline, prefer=provider)
        if fallback_chain:
            preferred = [inst for name in fallback_chain if (inst := self.registry.get(name)) is not None]
            seen = {inst.name for inst in preferred}
            chain = preferred + [c for c in chain if c.name not in seen]

        if not chain:
            return RouteResult(None, [], total_ms=(time.perf_counter() - started) * 1000)

        attempts: list[RouteAttempt] = []
        for index, candidate in enumerate(chain):
            use_model = (
                model
                if (index == 0 and candidate.name == provider)
                else _fallback_model(candidate.name, self.settings)
            )
            tools_for_call = tool_list if candidate.supports_tools else []
            if tool_list and not candidate.supports_tools:
                log.warning("%s no soporta tool calling: se envía sin herramientas", candidate.name)

            request = CompletionRequest(
                messages=list(messages),
                model=use_model,
                provider=candidate.name,
                tools=tools_for_call,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_s=self.settings.router.timeout_s,
            )
            self.bus.publish(
                LLM_REQUEST,
                source="router",
                provider=candidate.name,
                model=use_model,
                tokens_est=request.prompt_tokens_estimate(),
                tools=len(tools_for_call),
            )

            result, attempt = await self._call_with_retries(candidate, request)
            attempts.append(attempt)

            if result is not None:
                self.registry.report_success(candidate.name)
                self._account(candidate, result)
                total_ms = (time.perf_counter() - started) * 1000
                self.bus.publish(
                    LLM_RESPONSE,
                    source="router",
                    provider=candidate.name,
                    model=use_model,
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    cost_usd=round(result.cost_usd, 6),
                    latency_ms=round(result.latency_ms, 1),
                    finish_reason=result.finish_reason,
                )
                if index > 0:
                    self.bus.publish(
                        PROVIDER_FAILOVER,
                        source="router",
                        from_provider=provider,
                        to_provider=candidate.name,
                        reason=attempts[0].error,
                    )
                self._record_stats(candidate.name, use_model, result)
                return RouteResult(
                    result=result,
                    attempts=attempts,
                    provider_used=candidate.name,
                    model_used=use_model,
                    total_ms=total_ms,
                )

            self.registry.report_failure(candidate.name)
            if index + 1 < len(chain):
                log.warning("failover %s -> %s (%s)", candidate.name, chain[index + 1].name, attempt.error)

        return RouteResult(None, attempts, total_ms=(time.perf_counter() - started) * 1000)

    async def _call_with_retries(
        self, provider: LLMProvider, request: CompletionRequest
    ) -> tuple[CompletionResult | None, RouteAttempt]:
        max_retries = self.settings.router.max_retries
        last_error = ""
        for attempt in range(max_retries + 1):
            await self._throttle()
            try:
                result = await provider.complete(request)
                return result, RouteAttempt(provider.name, request.model, True, latency_ms=result.latency_ms)
            except ProviderError as exc:
                last_error = f"{exc.kind.value}: {exc}"
                if exc.kind in FATAL_FOR_PROVIDER:
                    break
                if exc.kind in RETRYABLE and attempt < max_retries:
                    delay = self.settings.router.backoff_base_s * (2**attempt) + random.uniform(0, 0.3)
                    log.info(
                        "reintento %d/%d a %s en %.1f s (%s)",
                        attempt + 1,
                        max_retries,
                        provider.name,
                        delay,
                        exc.kind.value,
                    )
                    await asyncio.sleep(delay)
                    continue
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = f"inesperado: {type(exc).__name__}: {exc}"
                break
        return None, RouteAttempt(provider.name, request.model, False, error=last_error)

    # -- contabilidad ----------------------------------------------------- #
    def _account(self, provider: LLMProvider, result: CompletionResult) -> None:
        """Registra tokens y coste en el budget guard compartido con el policy engine."""
        _ = provider
        self.budget.record_llm(result.usage.total, result.cost_usd)
        if self.budget.at_warning_threshold():
            self.bus.publish(
                "budget.threshold", source="router", pct=self.budget.snapshot()["usd_pct"], kind="usd"
            )

    def _record_stats(self, provider: str, model: str, result: CompletionResult) -> None:
        entry = self.stats.setdefault(
            provider, {"calls": 0, "tokens": 0, "cost_usd": 0.0, "ms": 0.0, "model": model, "errors": 0}
        )
        entry["calls"] += 1
        entry["tokens"] += result.usage.total
        entry["cost_usd"] = round(entry["cost_usd"] + result.cost_usd, 6)
        entry["ms"] += result.latency_ms
        entry["model"] = model

    async def health(self, *, force: bool = False) -> dict[str, Any]:
        health = await self.registry.health_all(force=force)
        return {
            name: {
                "ok": h.ok,
                "reason": h.reason,
                "latency_ms": round(h.latency_ms, 1),
                "has_key": h.has_key,
                "circuit_open": self.registry.circuit_state(name).is_open,
            }
            for name, h in health.items()
        }

    async def aclose(self) -> None:
        await self.registry.aclose()


def _guess_provider(model: str) -> str | None:
    """Deduce el proveedor del nombre del modelo (heurística configurable)."""
    low = model.lower()
    if "gpt" in low or "o1" in low or "o3" in low or "chatgpt" in low:
        return "openai"
    if "claude" in low or "opus" in low or "sonnet" in low or "haiku" in low:
        return "anthropic"
    if "gemini" in low or "gemma" in low:
        return "gemini"
    if ":" in low or "llama" in low or "qwen" in low or "mistral" in low or "phi" in low:
        return "ollama"
    return None


def _fallback_model(provider: str, settings: Settings) -> str:
    """Modelo a usar cuando el failover cambia de proveedor.

    Sale de `[router.fallback_models]` en la configuración: ningún nombre de modelo
    está hardcodeado en el código (principio P10), así que un rename del proveedor
    se resuelve editando el TOML y no esperando un release.
    """
    router_cfg = settings.router
    configured = router_cfg.fallback_models.get(provider)
    if configured:
        return configured
    if provider == "ollama":
        return router_cfg.model_offline
    return router_cfg.model_general
