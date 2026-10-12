"""Tests de los proveedores.

Sin red: se verifica la CONSTRUCCIÓN del payload (función pura) y el PARSEO de
una respuesta real capturada. Si un proveedor cambia su API, estos tests fallan
antes que el usuario (ADR-0001).
"""

from __future__ import annotations

import pytest

from jarvis.providers.base import (
    CompletionRequest,
    Message,
    ProviderError,
    ProviderErrorKind,
    ToolCall,
    ToolSpec,
    Usage,
    safe_json_loads,
)

TOOLS = [
    ToolSpec(
        name="system.info",
        description="Devuelve el estado del sistema",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    )
]
MESSAGES = [Message(role="system", content="Eres Jarvis"), Message(role="user", content="hola")]


def _request(**kwargs) -> CompletionRequest:
    base = {"messages": MESSAGES, "model": "test-model", "tools": TOOLS}
    base.update(kwargs)
    return CompletionRequest(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# OpenAI
# --------------------------------------------------------------------------- #
def test_openai_payload_shape() -> None:
    from jarvis.providers.openai_provider import build_payload

    payload = build_payload(_request())
    assert payload["model"] == "test-model"
    assert payload["messages"][0] == {"role": "system", "content": "Eres Jarvis"}
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["function"]["name"] == "system.info"
    assert payload["tool_choice"] == "auto"
    assert payload["stream"] is False


def test_openai_parse_response_with_tool_call() -> None:
    from jarvis.providers.openai_provider import parse_response

    data = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_abc",
                            "function": {"name": "system.disk", "arguments": '{"mount": "/"}'},
                        }
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 15},
    }
    text, calls, usage, finish = parse_response(data)
    assert text == ""
    assert calls[0].skill == "system.disk"
    assert calls[0].arguments == {"mount": "/"}
    assert usage.input_tokens == 120
    assert finish == "tool_calls"


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #
def test_anthropic_extracts_system_prompt() -> None:
    from jarvis.providers.anthropic_provider import build_payload

    payload = build_payload(_request())
    assert payload["system"] == "Eres Jarvis"
    assert all(m["role"] != "system" for m in payload["messages"])
    assert payload["tools"][0]["input_schema"]["type"] == "object"
    assert "max_tokens" in payload


def test_anthropic_parse_response_with_tool_use() -> None:
    from jarvis.providers.anthropic_provider import parse_response

    data = {
        "stop_reason": "tool_use",
        "content": [
            {"type": "text", "text": "Voy a mirar el disco."},
            {"type": "tool_use", "id": "toolu_1", "name": "system.disk", "input": {"mount": "/"}},
        ],
        "usage": {"input_tokens": 200, "output_tokens": 40, "cache_read_input_tokens": 150},
    }
    text, calls, usage, finish = parse_response(data)
    assert "disco" in text
    assert calls[0].skill == "system.disk"
    assert usage.cached_tokens == 150
    assert finish == "tool_use"


def test_anthropic_tool_result_message_shape() -> None:
    message = Message(role="tool", content="42% usado", tool_call_id="toolu_1")
    payload = message.to_anthropic()
    assert payload["role"] == "user"
    assert payload["content"][0]["type"] == "tool_result"
    assert payload["content"][0]["tool_use_id"] == "toolu_1"


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #
def test_gemini_payload_uses_model_role_and_function_declarations() -> None:
    from jarvis.providers.gemini_provider import build_payload

    payload = build_payload(_request())
    assert payload["systemInstruction"]["parts"][0]["text"] == "Eres Jarvis"
    assert payload["contents"][0]["role"] == "user"
    assert payload["generationConfig"]["temperature"] == 0.3
    declarations = payload["tools"][0]["functionDeclarations"]
    # Gemini no admite puntos en los nombres de función.
    assert declarations[0]["name"] == "system_info"


def test_gemini_parse_response_with_function_call() -> None:
    from jarvis.providers.gemini_provider import parse_response

    data = {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "parts": [
                        {"text": "Consulto el disco."},
                        {"functionCall": {"name": "system_disk", "args": {"mount": "/"}}},
                    ]
                },
            }
        ],
        "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 10},
    }
    text, calls, usage, finish = parse_response(data)
    assert text == "Consulto el disco."
    assert calls[0].skill == "system.disk"  # se restauran los puntos
    assert usage.total == 60
    assert finish == "STOP"


# --------------------------------------------------------------------------- #
# Ollama
# --------------------------------------------------------------------------- #
def test_ollama_payload_shape() -> None:
    from jarvis.providers.ollama_provider import build_payload

    payload = build_payload(_request())
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0.3
    assert payload["tools"][0]["function"]["name"] == "system.info"


def test_ollama_parse_response() -> None:
    from jarvis.providers.ollama_provider import parse_response

    data = {
        "model": "qwen2.5:7b",
        "message": {"content": "Hola.", "tool_calls": [{"function": {"name": "time.now", "arguments": {}}}]},
        "prompt_eval_count": 30,
        "eval_count": 8,
    }
    text, calls, usage = parse_response(data)
    assert text == "Hola."
    assert calls[0].skill == "time.now"
    assert usage.total == 38


@pytest.mark.asyncio
async def test_ollama_unreachable_raises_network_error() -> None:
    """Debe dar un mensaje accionable, no un traceback de httpx."""
    from jarvis.providers.ollama_provider import OllamaProvider

    provider = OllamaProvider(base_url="http://127.0.0.1:1", timeout_s=0.5)
    with pytest.raises(ProviderError) as exc:
        await provider.complete(_request(model="cualquiera"))
    assert exc.value.kind is ProviderErrorKind.NETWORK
    assert "Ollama" in str(exc.value)
    await provider.aclose()


# --------------------------------------------------------------------------- #
# Echo (offline)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_echo_provider_answers_offline() -> None:
    from jarvis.providers.echo_provider import EchoProvider

    provider = EchoProvider()
    result = await provider.complete(_request(tools=[]))
    assert result.text
    assert result.cost_usd == 0.0
    assert provider.available() == (True, "")


@pytest.mark.asyncio
async def test_echo_recognizes_chitchat_in_spanish() -> None:
    from jarvis.providers.echo_provider import EchoProvider

    provider = EchoProvider()
    result = await provider.complete(
        CompletionRequest(messages=[Message(role="user", content="hola")], model="echo", tools=[])
    )
    assert "órdenes" in result.text


# --------------------------------------------------------------------------- #
# Utilidades compartidas
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 2}\n```', {"a": 2}),
        ('```\n{"a": 3}\n```', {"a": 3}),
        ('texto antes {"a": 4} texto después', {"a": 4}),
        ("", {}),
        ("no hay json aquí", {}),
    ],
)
def test_safe_json_loads_is_forgiving(raw: str, expected: dict) -> None:
    assert safe_json_loads(raw) == expected


@pytest.mark.parametrize(
    "status,kind",
    [
        (401, ProviderErrorKind.AUTH),
        (403, ProviderErrorKind.AUTH),
        (404, ProviderErrorKind.MODEL_NOT_FOUND),
        (429, ProviderErrorKind.RATE_LIMIT),
        (400, ProviderErrorKind.BAD_REQUEST),
        (500, ProviderErrorKind.SERVER),
        (503, ProviderErrorKind.SERVER),
    ],
)
def test_status_classification(status: int, kind: ProviderErrorKind) -> None:
    error = __import__("jarvis.providers.base", fromlist=["LLMProvider"]).LLMProvider.classify_status(
        status, "test"
    )
    assert error.kind is kind


def test_rate_limit_and_server_errors_are_retryable() -> None:
    from jarvis.providers.base import LLMProvider

    assert LLMProvider.classify_status(429, "x").retryable
    assert LLMProvider.classify_status(503, "x").retryable
    assert not LLMProvider.classify_status(401, "x").retryable


def test_cost_estimation() -> None:
    from jarvis.providers.base import LLMProvider

    class P(LLMProvider):
        name = "p"
        pricing = (3.0, 15.0)

        async def complete(self, request):  # pragma: no cover
            raise NotImplementedError

    provider = P()
    cost = provider.estimate_cost(Usage(input_tokens=1_000_000, output_tokens=1_000_000))
    assert cost == pytest.approx(18.0)


def test_tool_call_openai_serialization() -> None:
    message = Message(
        role="assistant",
        content="",
        tool_calls=[ToolCall(id="c1", skill="apps.launch", arguments={"app": "firefox"})],
    )
    payload = message.to_openai()
    assert payload["tool_calls"][0]["function"]["name"] == "apps.launch"
    assert '"firefox"' in payload["tool_calls"][0]["function"]["arguments"]
