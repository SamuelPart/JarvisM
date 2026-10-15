"""Registro y fábrica de proveedores.

Construye las instancias desde la configuración y mantiene la cadena de
failover. No sabe nada de HTTP: solo de qué proveedores existen y cuáles
están disponibles ahora mismo.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from jarvis.config.settings import Settings
from jarvis.providers.anthropic_provider import AnthropicProvider
from jarvis.providers.base import LLMProvider, ProviderHealth
from jarvis.providers.echo_provider import EchoProvider
from jarvis.providers.gemini_provider import GeminiProvider
from jarvis.providers.nvidia_provider import NvidiaProvider
from jarvis.providers.ollama_provider import OllamaProvider
from jarvis.providers.openai_provider import OpenAIProvider

_FACTORIES: dict[str, type[LLMProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "nvidia": NvidiaProvider,
    "ollama": OllamaProvider,
    "echo": EchoProvider,
}

#: Proveedores que no salen a la nube, en orden de capacidad decreciente:
#: Ollama razona de verdad, `echo` solo cierra el circuito sin gastar tokens ni red.
LOCAL_PROVIDERS: tuple[str, ...] = ("ollama", "echo")


@dataclass(slots=True)
class CircuitState:
    failures: int = 0
    open_until: float = 0.0

    @property
    def is_open(self) -> bool:
        return time.time() < self.open_until


@dataclass
class ProviderRegistry:
    settings: Settings
    _providers: dict[str, LLMProvider] = field(default_factory=dict)
    _circuits: dict[str, CircuitState] = field(default_factory=dict)
    _health_cache: dict[str, ProviderHealth] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, settings: Settings) -> ProviderRegistry:
        registry = cls(settings=settings)
        router = settings.router
        for name, factory in _FACTORIES.items():
            cfg = getattr(settings.providers, name, None)
            enabled = cfg.enabled if cfg is not None else True
            if name in {"ollama", "echo"}:
                base_url = getattr(cfg, "base_url", "") if cfg else ""
                registry._providers[name] = factory(
                    base_url=base_url, api_key=None, timeout_s=router.timeout_s
                )
                continue
            if not enabled or cfg is None:
                continue
            kwargs: dict[str, object] = {
                "base_url": cfg.base_url,
                "api_key": cfg.resolve_api_key(),
                "timeout_s": router.timeout_s,
            }
            if name == "anthropic":
                kwargs["anthropic_version"] = cfg.anthropic_version
            registry._providers[name] = factory(**kwargs)  # type: ignore[arg-type]
        return registry

    # -- acceso ----------------------------------------------------------- #
    @property
    def names(self) -> list[str]:
        return list(self._providers)

    def get(self, name: str) -> LLMProvider | None:
        return self._providers.get(name)

    def chain(self, *, strict_offline: bool = False, prefer: str | None = None) -> list[LLMProvider]:
        """Orden de uso real: preferencia -> cadena configurada -> ollama -> echo.

        `strict_offline` (privacidad.offline explícito) corta toda salida a la nube.
        Ojo: la AUSENCIA de claves no debe vaciar la cadena — cada proveedor decide
        en `available()` si puede usarse, y así un proveedor propio registrado por
        el usuario (o los tests) sigue funcionando.
        """
        ordered: list[str] = []
        if strict_offline or self.settings.privacy.offline:
            # `prefer` manda también aquí si es local: pedir `--provider echo` en
            # modo privado debe dar echo y no un Ollama que quizá no está levantado.
            ordered = [p for p in (prefer,) if p in LOCAL_PROVIDERS]
            ordered += list(LOCAL_PROVIDERS)
        else:
            if prefer and prefer in self._providers:
                ordered.append(prefer)
            ordered += [p for p in self.settings.router.default_chain if p in self._providers]
            ordered += ["ollama", "echo"]
        seen: set[str] = set()
        result: list[LLMProvider] = []
        for name in ordered:
            if name in seen:
                continue
            seen.add(name)
            provider = self._providers.get(name)
            if provider is None:
                continue
            circuit = self._circuits.get(name)
            if circuit and circuit.is_open:
                continue
            ok, _ = provider.available()
            if not ok and name != "echo":
                continue
            result.append(provider)
        return result

    # -- circuit breaker -------------------------------------------------- #
    def report_failure(self, name: str) -> None:
        state = self._circuits.setdefault(name, CircuitState())
        state.failures += 1
        if state.failures >= self.settings.router.circuit_breaker_failures:
            state.open_until = time.time() + self.settings.router.circuit_breaker_cooldown_s
            state.failures = 0

    def report_success(self, name: str) -> None:
        state = self._circuits.get(name)
        if state:
            state.failures = 0
            state.open_until = 0.0

    def circuit_state(self, name: str) -> CircuitState:
        return self._circuits.setdefault(name, CircuitState())

    # -- salud ------------------------------------------------------------ #
    async def health_all(self, *, force: bool = False) -> dict[str, ProviderHealth]:
        out: dict[str, ProviderHealth] = {}
        ttl = self.settings.router.health_cache_s
        for name, provider in self._providers.items():
            cached = self._health_cache.get(name)
            if cached and not force and (time.time() - cached.checked_at) < ttl:
                out[name] = cached
                continue
            health = await provider.health()
            self._health_cache[name] = health
            out[name] = health
        return out

    async def aclose(self) -> None:
        for provider in self._providers.values():
            await provider.aclose()
