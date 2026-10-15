"""Proveedor NVIDIA NIM: es OpenAI-compatible, así que se reutiliza casi todo.

Lo que se prueba aquí no es "sabe hablar con NIM" (eso es de `test_providers`),
sino las tres cosas que sí son propias: el mensaje de error honesto, el endpoint
por defecto y que la tabla de modelos por proveedor resuelva bien.
"""

from __future__ import annotations

import pytest

from jarvis.providers.base import ProviderError, ProviderErrorKind, request_model_for_health
from jarvis.providers.nvidia_provider import DEFAULT_BASE_URL, NvidiaProvider


def test_defaults_point_to_nvidia_not_openai() -> None:
    provider = NvidiaProvider(api_key="nvapi-x")
    assert provider.name == "nvidia"
    assert provider.base_url == DEFAULT_BASE_URL
    assert provider.base_url == "https://integrate.api.nvidia.com/v1"


def test_available_reports_the_real_missing_key() -> None:
    """El mensaje debe nombrar la variable correcta, no la de otro proveedor."""
    ok, reason = NvidiaProvider(api_key=None).available()
    assert not ok
    assert "NVIDIA_API_KEY" in reason
    assert "OPENAI" not in reason

    ok, reason = NvidiaProvider(api_key="nvapi-x").available()
    assert ok
    assert reason == ""


async def test_complete_without_key_raises_no_key() -> None:
    provider = NvidiaProvider(api_key=None)
    from jarvis.providers.base import CompletionRequest, Message

    with pytest.raises(ProviderError) as exc:
        await provider.complete(CompletionRequest(messages=[Message(role="user", content="hola")], model="m"))
    assert exc.value.kind is ProviderErrorKind.NO_KEY
    assert "NVIDIA_API_KEY" in str(exc.value)


def _patch_router_config(monkeypatch, **overrides) -> None:
    """`request_model_for_health` lee la config global, así que se parchea esa.

    (El import ocurre dentro de la función, de modo que parchear el atributo del
    módulo es suficiente y no hace falta tocar la config real del usuario.)
    """
    from types import SimpleNamespace

    router = SimpleNamespace(
        fallback_models={"nvidia": "deepseek-ai/deepseek-v3.2"},
        model_cheap="gemini-2.5-flash-lite",
        model_offline="qwen2.5:7b-instruct",
    )
    for key, value in overrides.items():
        setattr(router, key, value)
    monkeypatch.setattr("jarvis.config.settings.get_settings", lambda: SimpleNamespace(router=router))


def test_health_uses_a_model_nvidia_knows(monkeypatch) -> None:
    """Antes el ping iba con el modelo barato de OTRO proveedor -> 404 falso."""
    _patch_router_config(monkeypatch)
    assert request_model_for_health(NvidiaProvider(api_key="nvapi-x")) == "deepseek-ai/deepseek-v3.2"


def test_health_model_falls_back_when_unconfigured(monkeypatch) -> None:
    _patch_router_config(monkeypatch, fallback_models={})
    assert request_model_for_health(NvidiaProvider(api_key="nvapi-x")) == "gemini-2.5-flash-lite"


def test_health_for_ollama_uses_the_local_model(monkeypatch) -> None:
    """Ollama mantiene su excepción: su modelo es `model_offline`, no el de fallback."""
    from jarvis.providers.ollama_provider import OllamaProvider

    _patch_router_config(monkeypatch)
    assert request_model_for_health(OllamaProvider()) == "qwen2.5:7b-instruct"


def test_registry_builds_nvidia_from_settings(settings, monkeypatch) -> None:
    from jarvis.providers.registry import ProviderRegistry

    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-de-prueba")
    settings.providers.nvidia.api_key_env = "NVIDIA_API_KEY"
    registry = ProviderRegistry.from_settings(settings)
    provider = registry.get("nvidia")
    assert isinstance(provider, NvidiaProvider)
    assert provider.api_key == "nvapi-de-prueba"


def test_nvidia_is_in_the_default_chain_right_after_gemini() -> None:
    """Cascada por defecto: gratis primero, de pago al final."""
    from jarvis.config.settings import RouterConfig

    chain = RouterConfig().default_chain
    assert chain[:2] == ["gemini", "nvidia"]
    assert chain.index("nvidia") < chain.index("openai")


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("deepseek-ai/deepseek-v3.2", "nvidia"),
        ("meta/llama-4-scout-17b-16e-instruct", "nvidia"),
        ("qwen2.5:7b-instruct", "ollama"),  # tag local: los dos puntos lo delatan
        ("llama3.2", "ollama"),
        ("gemini-3.7-flash", "gemini"),
        ("gpt-5.6-luna", "openai"),
        ("claude-sonnet-5", "anthropic"),
    ],
)
def test_model_name_routing(model: str, expected: str) -> None:
    """`org/modelo` no puede confundirse con un tag de Ollama."""
    from jarvis.core.router import _guess_provider

    assert _guess_provider(model) == expected


def test_nvidia_key_counts_as_cloud_for_offline_detection(settings, monkeypatch) -> None:
    """Con clave de NVIDIA no estamos en modo local: `effective_offline` es False."""
    for var in ("GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "NVIDIA_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    settings.privacy.offline = False
    for name in ("gemini", "openai", "anthropic", "nvidia"):
        getattr(settings.providers, name).api_key = None
    assert settings.effective_offline(), "sin ninguna clave debe estar offline"

    settings.providers.nvidia.api_key = "nvapi-x"  # type: ignore[assignment]
    assert not settings.effective_offline()
