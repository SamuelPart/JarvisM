"""Proveedor OpenAI-compatible (OpenAI, Groq, OpenRouter, vLLM, LM Studio...)."""

from __future__ import annotations

import json
import time
from typing import Any

from jarvis.providers.base import (
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    ProviderError,
    ProviderErrorKind,
    ToolCall,
    Usage,
    safe_json_loads,
)


def build_payload(request: CompletionRequest) -> dict[str, Any]:
    """Función pura: el test fija este payload contra la API real."""
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": [m.to_openai() for m in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "stream": False,
    }
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in request.tools
        ]
        payload["tool_choice"] = "auto"
    payload.update(request.extra)
    return payload


def parse_response(data: dict[str, Any]) -> tuple[str, list[ToolCall], Usage, str]:
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    text = message.get("content") or ""
    calls: list[ToolCall] = []
    for raw in message.get("tool_calls") or []:
        fn = raw.get("function") or {}
        args = fn.get("arguments")
        parsed = safe_json_loads(args) if isinstance(args, str) else (args or {})
        calls.append(
            ToolCall(
                id=raw.get("id") or f"call_{len(calls)}",
                skill=fn.get("name", ""),
                arguments=parsed,
                raw=raw,
            )
        )
    raw_usage = data.get("usage") or {}
    usage = Usage(
        input_tokens=int(raw_usage.get("prompt_tokens") or 0),
        output_tokens=int(raw_usage.get("completion_tokens") or 0),
        cached_tokens=int((raw_usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0),
    )
    return text, calls, usage, choice.get("finish_reason") or ""


class OpenAIProvider(LLMProvider):
    name = "openai"
    supports_tools = True
    supports_vision = True
    supports_stream = True
    pricing = (0.20, 1.20)  # referencia; el router usa config, no este valor

    def __init__(
        self,
        *,
        base_url: str = "https://api.openai.com/v1",
        api_key: str | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        super().__init__(
            base_url=base_url or "https://api.openai.com/v1", api_key=api_key, timeout_s=timeout_s
        )

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "falta OPENAI_API_KEY"
        return True, ""

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        if not self.api_key:
            raise ProviderError(ProviderErrorKind.NO_KEY, "sin OPENAI_API_KEY", provider=self.name)
        started = time.perf_counter()
        url = f"{self.base_url}/chat/completions"
        try:
            response = await self.client.post(
                url, headers=self._headers(), json=build_payload(request), timeout=request.timeout_s
            )
        except Exception as exc:
            kind = ProviderErrorKind.TIMEOUT if "timeout" in str(exc).lower() else ProviderErrorKind.NETWORK
            raise ProviderError(kind, str(exc), provider=self.name, retryable=True) from exc

        if response.status_code != 200:
            raise self.classify_status(response.status_code, self.name, response.text)

        data = response.json()
        text, calls, usage, finish = parse_response(data)
        latency = (time.perf_counter() - started) * 1000
        result = CompletionResult(
            text=text,
            tool_calls=calls,
            provider=self.name,
            model=data.get("model", request.model),
            usage=usage,
            latency_ms=latency,
            finish_reason=finish,
            raw={"usage": data.get("usage")},
        )
        result.cost_usd = self.estimate_cost(usage)
        return result

    async def stream(self, request: CompletionRequest):  # pragma: no cover - red real
        payload = build_payload(request)
        payload["stream"] = True
        buffer: dict[int, dict[str, str]] = {}
        started = time.perf_counter()
        async with self.client.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers=self._headers(),
            json=payload,
            timeout=request.timeout_s,
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise self.classify_status(response.status_code, self.name, body.decode(errors="replace"))
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                chunk = line[6:].strip()
                if chunk == "[DONE]":
                    break
                data = json.loads(chunk)
                delta = (data.get("choices") or [{}])[0].get("delta") or {}
                if text := delta.get("content"):
                    yield _chunk(text=text)
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = buffer.setdefault(idx, {"id": "", "name": "", "args": ""})
                    slot["id"] = slot["id"] or tc.get("id", "")
                    fn = tc.get("function") or {}
                    slot["name"] += fn.get("name", "")
                    slot["args"] += fn.get("arguments", "")
        calls = [
            ToolCall(id=v["id"] or f"call_{i}", skill=v["name"], arguments=safe_json_loads(v["args"]))
            for i, v in sorted(buffer.items())
            if v["name"]
        ]
        yield _chunk(
            done=True,
            calls=calls,
            ms=(time.perf_counter() - started) * 1000,
            model=request.model,
            provider=self.name,
        )


def _chunk(
    *,
    text: str = "",
    done: bool = False,
    calls: list[ToolCall] | None = None,
    ms: float = 0.0,
    model: str = "",
    provider: str = "",
) -> Any:
    from jarvis.providers.base import Chunk

    result = None
    if done:
        result = CompletionResult(
            text="", tool_calls=calls or [], provider=provider, model=model, latency_ms=ms, usage=Usage()
        )
    return Chunk(delta=text, tool_calls=calls or [], done=done, result=result)
