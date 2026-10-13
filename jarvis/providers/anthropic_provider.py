"""Proveedor Anthropic (Claude). Endpoint /v1/messages.

Particularidades respecto a OpenAI:
- el system prompt va en un campo propio `system`, no como mensaje;
- los tools usan `input_schema`;
- las respuestas mezclan bloques `text` y `tool_use`;
- el resultado de un tool se devuelve como rol `user` con bloque `tool_result`.
"""

from __future__ import annotations

import time
from typing import Any

from jarvis.providers.base import (
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    Message,
    ProviderError,
    ProviderErrorKind,
    ToolCall,
    Usage,
)


def split_system(messages: list[Message]) -> tuple[str, list[Message]]:
    """Extrae y concatena los mensajes de sistema (Anthropic los quiere aparte)."""
    system_parts = [m.content for m in messages if m.role == "system" and m.content]
    rest = [m for m in messages if m.role != "system"]
    return "\n\n".join(system_parts), rest


def build_payload(request: CompletionRequest) -> dict[str, Any]:
    system, rest = split_system(request.messages)
    payload: dict[str, Any] = {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "temperature": request.temperature,
        "messages": [m.to_anthropic() for m in rest],
        "stream": False,
    }
    if system:
        payload["system"] = system
    if request.tools:
        payload["tools"] = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in request.tools
        ]
    payload.update(request.extra)
    return payload


def parse_response(data: dict[str, Any]) -> tuple[str, list[ToolCall], Usage, str]:
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in data.get("content") or []:
        kind = block.get("type")
        if kind == "text":
            text_parts.append(block.get("text", ""))
        elif kind == "tool_use":
            calls.append(
                ToolCall(
                    id=block.get("id", f"toolu_{len(calls)}"),
                    skill=block.get("name", ""),
                    arguments=block.get("input") or {},
                    raw=block,
                )
            )
    raw_usage = data.get("usage") or {}
    usage = Usage(
        input_tokens=int(raw_usage.get("input_tokens") or 0),
        output_tokens=int(raw_usage.get("output_tokens") or 0),
        cached_tokens=int(raw_usage.get("cache_read_input_tokens") or 0),
    )
    return "\n".join(p for p in text_parts if p), calls, usage, data.get("stop_reason") or ""


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    supports_tools = True
    supports_vision = True
    supports_stream = True
    pricing = (2.00, 10.00)

    def __init__(
        self,
        *,
        base_url: str = "https://api.anthropic.com",
        api_key: str | None = None,
        timeout_s: float = 30.0,
        anthropic_version: str = "2023-06-01",
    ) -> None:
        super().__init__(
            base_url=base_url or "https://api.anthropic.com", api_key=api_key, timeout_s=timeout_s
        )
        self.anthropic_version = anthropic_version

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "falta ANTHROPIC_API_KEY"
        return True, ""

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key or "",
            "anthropic-version": self.anthropic_version,
            "content-type": "application/json",
        }

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        if not self.api_key:
            raise ProviderError(ProviderErrorKind.NO_KEY, "sin ANTHROPIC_API_KEY", provider=self.name)
        started = time.perf_counter()
        try:
            response = await self.client.post(
                f"{self.base_url}/v1/messages",
                headers=self._headers(),
                json=build_payload(request),
                timeout=request.timeout_s,
            )
        except Exception as exc:
            kind = ProviderErrorKind.TIMEOUT if "timeout" in str(exc).lower() else ProviderErrorKind.NETWORK
            raise ProviderError(kind, str(exc), provider=self.name, retryable=True) from exc

        if response.status_code != 200:
            raise self.classify_status(response.status_code, self.name, response.text)

        data = response.json()
        text, calls, usage, finish = parse_response(data)
        result = CompletionResult(
            text=text,
            tool_calls=calls,
            provider=self.name,
            model=data.get("model", request.model),
            usage=usage,
            latency_ms=(time.perf_counter() - started) * 1000,
            finish_reason=finish,
            raw={"usage": data.get("usage")},
        )
        result.cost_usd = self.estimate_cost(usage)
        return result
