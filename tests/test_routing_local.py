"""Regresiones del enrutado cuando NO hay nube disponible.

Estos tres bugs se encontraron probando el instalador en un Kali limpio (sin
claves de API), que es exactamente el escenario del primer arranque:

1. `--provider echo` era ignorado: el router forzaba Ollama al estar offline,
   así que el usuario pedía el proveedor de eco y recibía reintentos contra un
   demonio apagado.
2. Un "connection refused" contra Ollama se reintentaba 2 veces (~3 s) antes de
   hacer failover, cuando reintentar contra un puerto cerrado no puede funcionar.
3. En modo privado (`privacy.offline`) ni siquiera se miraba `prefer`, con lo
   que `--provider echo` tampoco servía ahí.

Los tres son de latencia/UX, no de seguridad: ninguno debe "arreglarse"
relajando los guardarraíles de policy.
"""

from __future__ import annotations

import time

import pytest

from jarvis.core.router import Router
from jarvis.providers.base import (
    RETRYABLE_KINDS,
    CompletionRequest,
    Message,
    ProviderError,
    ProviderErrorKind,
)
from jarvis.providers.echo_provider import EchoProvider
from jarvis.providers.ollama_provider import OllamaProvider
from jarvis.providers.registry import LOCAL_PROVIDERS, ProviderRegistry


def _request() -> CompletionRequest:
    return CompletionRequest(messages=[Message(role="user", content="hola")], model="test", tools=[])


# --------------------------------------------------------------------------- #
# 1. La cadena local que fija la CLI se respeta
# --------------------------------------------------------------------------- #
def test_model_for_respects_pinned_echo(settings) -> None:
    """`jarvis chat --provider echo` debe dar echo, no Ollama."""
    assert settings.effective_offline(), "el test asume un entorno sin claves"
    settings.router.default_chain = ["echo", "gemini", "anthropic", "openai", "ollama"]
    provider, model = Router(settings).model_for()
    assert provider == "echo"
    assert model == settings.router.fallback_models["echo"]


def test_model_for_defaults_to_ollama(settings) -> None:
    """Sin preferencia explícita gana el proveedor local más capaz."""
    assert settings.effective_offline()
    settings.router.default_chain = ["gemini", "anthropic", "openai", "ollama"]
    provider, model = Router(settings).model_for()
    assert provider == "ollama"
    assert model == settings.router.model_offline


def test_model_for_offline_profile_ignores_cloud(settings) -> None:
    """El perfil `offline` pide local aunque haya claves de nube."""
    settings.providers.gemini.api_key = "clave-de-prueba"
    assert not settings.effective_offline()
    settings.router.default_chain = ["gemini", "ollama", "echo"]
    assert Router(settings).model_for("offline")[0] == "ollama"


def test_chain_honors_prefer_in_strict_offline(settings) -> None:
    """Modo privado + `--provider echo` -> echo primero, no Ollama."""
    settings.privacy.offline = True
    registry = ProviderRegistry.from_settings(settings)
    chain = [p.name for p in registry.chain(strict_offline=True, prefer="echo")]
    assert chain[0] == "echo"
    assert "ollama" in chain


def test_chain_strict_offline_never_includes_cloud(settings) -> None:
    """Guardarraíl: en modo privado no puede colarse un proveedor de nube."""
    settings.privacy.offline = True
    settings.providers.openai.api_key = "clave-de-prueba"
    registry = ProviderRegistry.from_settings(settings)
    names = {p.name for p in registry.chain(strict_offline=True, prefer="openai")}
    assert names <= set(LOCAL_PROVIDERS)


# --------------------------------------------------------------------------- #
# 2. Un puerto cerrado no se reintenta (failover inmediato)
# --------------------------------------------------------------------------- #
async def test_connection_refused_fails_over_without_backoff(settings) -> None:
    """Ollama apagado -> se salta a echo ya, sin perder el backoff."""
    settings.router.default_chain = ["ollama", "echo"]
    settings.router.max_retries = 2
    settings.router.backoff_base_s = 0.8

    registry = ProviderRegistry(settings=settings)
    # Puerto 1: cerrado garantizado, el connect se rechaza al instante.
    registry._providers = {
        "ollama": OllamaProvider(base_url="http://127.0.0.1:1", timeout_s=0.5),
        "echo": EchoProvider(),
    }

    started = time.perf_counter()
    result = await Router(settings, registry=registry).complete(messages=list(_request().messages))
    elapsed = time.perf_counter() - started

    assert result.provider_used == "echo"
    assert len(result.attempts) == 2, "un intento por proveedor: sin reintentos contra el puerto cerrado"
    assert result.attempts[0].provider == "ollama"
    assert not result.attempts[0].ok
    assert elapsed < 1.0, f"el failover tardó {elapsed:.2f} s (¿se reintentó el connection refused?)"


async def test_transient_network_error_still_retries(settings) -> None:
    """Un timeout de lectura sí es recuperable: ahí el backoff se mantiene."""
    settings.router.default_chain = ["flaky"]
    settings.router.max_retries = 2
    settings.router.backoff_base_s = 0.01

    class Flaky(OllamaProvider):
        """Falla siempre, pero con un error que SÍ merece reintento."""

        name = "flaky"
        calls = 0

        async def complete(self, request):  # type: ignore[no-untyped-def]
            Flaky.calls += 1
            raise ProviderError(
                ProviderErrorKind.TIMEOUT, "timeout de lectura", provider=self.name, retryable=True
            )

    registry = ProviderRegistry(settings=settings)
    flaky = Flaky(base_url="http://127.0.0.1:1", timeout_s=0.2)
    registry._providers = {"flaky": flaky}

    result = await Router(settings, registry=registry).complete(messages=list(_request().messages))

    assert Flaky.calls == 3, "timeout retryable: 1 intento + 2 reintentos"
    assert not result.provider_used, "sin más cadena: no hay proveedor que responda"
    assert not result.attempts[0].ok
    assert result.attempts[0].error.startswith("timeout")
    await flaky.aclose()


# --------------------------------------------------------------------------- #
# 3. El tri-estado de `retryable`
# --------------------------------------------------------------------------- #
def test_should_retry_uses_kind_when_unspecified() -> None:
    assert ProviderError(ProviderErrorKind.NETWORK, "x").should_retry
    assert ProviderError(ProviderErrorKind.SERVER, "x").should_retry
    assert not ProviderError(ProviderErrorKind.AUTH, "x").should_retry
    assert not ProviderError(ProviderErrorKind.NO_KEY, "x").should_retry


def test_explicit_retryable_overrides_kind() -> None:
    """El caso que motivó el tri-estado: NETWORK que NO debe reintentarse."""
    refused = ProviderError(ProviderErrorKind.NETWORK, "connection refused", retryable=False)
    assert not refused.should_retry
    assert ProviderErrorKind.NETWORK in RETRYABLE_KINDS  # el tipo sigue siendo reintentable


def test_classify_status_still_marks_429_and_503_retryable() -> None:
    """Compatibilidad: el mapeo HTTP explícito no cambia."""
    from jarvis.providers.base import LLMProvider

    assert LLMProvider.classify_status(429, "x").should_retry
    assert LLMProvider.classify_status(503, "x").should_retry
    assert not LLMProvider.classify_status(401, "x").should_retry


@pytest.mark.parametrize("kind", sorted(RETRYABLE_KINDS, key=lambda k: k.value))
def test_every_retryable_kind_is_reachable(kind: ProviderErrorKind) -> None:
    assert ProviderError(kind, "x").should_retry
