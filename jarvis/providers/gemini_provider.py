"""Proveedor Google Gemini (Generative Language API, v1beta).

Particularidades:
- la clave puede ir por query param `key=` o por header `x-goog-api-key`;
- los roles son `user` / `model` (no `assistant`);
- el system prompt va en `systemInstruction`;
- los tools usan `functionDeclarations` y las respuestas `functionCall`.
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
    safe_json_loads,
)


def convert_messages(messages: list[Message]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Devuelve (systemInstruction, contents). Los tool results van como `functionResponse`."""
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []
    for msg in messages:
        if msg.role == "system":
            if msg.content:
                system_parts.append(msg.content)
            continue
        if msg.role == "tool":
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": msg.name or "tool",
                                "response": {"result": msg.content},
                            }
                        }
                    ],
                }
            )
            continue
        parts: list[dict[str, Any]] = []
        if msg.content:
            parts.append({"text": msg.content})
        for tc in msg.tool_calls:
            parts.append({"functionCall": {"name": tc.skill, "args": tc.arguments}})
        contents.append(
            {"role": "model" if msg.role == "assistant" else "user", "parts": parts or [{"text": ""}]}
        )
    system_instruction = {"parts": [{"text": "\n\n".join(system_parts)}]} if system_parts else None
    return system_instruction, contents


def build_payload(request: CompletionRequest) -> dict[str, Any]:
    system_instruction, contents = convert_messages(request.messages)
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_tokens,
        },
    }
    if system_instruction:
        payload["systemInstruction"] = system_instruction
    if request.tools:
        payload["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": t.name.replace(".", "_"),  # Gemini no admite puntos en nombres
                        "description": t.description,
                        "parameters": t.parameters,
                    }
                    for t in request.tools
                ]
            }
        ]
    payload.update(request.extra)
    return payload


def parse_response(data: dict[str, Any]) -> tuple[str, list[ToolCall], Usage, str]:
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    finish = ""
    for candidate in data.get("candidates") or []:
        finish = candidate.get("finishReason") or finish
        for part in (candidate.get("content") or {}).get("parts") or []:
            if "text" in part:
                text_parts.append(part["text"])
            if fc := part.get("functionCall"):
                args = fc.get("args")
                calls.append(
                    ToolCall(
                        id=f"gemini_{len(calls)}",
                        skill=str(fc.get("name", "")).replace("_", "."),
                        arguments=args if isinstance(args, dict) else safe_json_loads(str(args)),
                        raw=fc,
                    )
                )
    meta = data.get("usageMetadata") or {}
    usage = Usage(
        input_tokens=int(meta.get("promptTokenCount") or 0),
        output_tokens=int(meta.get("candidatesTokenCount") or 0),
        cached_tokens=int(meta.get("cachedContentTokenCount") or 0),
    )
    return "".join(text_parts), calls, usage, finish


class GeminiProvider(LLMProvider):
    name = "gemini"
    supports_tools = True
    supports_vision = True
    supports_stream = True
    pricing = (0.10, 0.40)

    def __init__(
        self,
        *,
        base_url: str = "https://generativelanguage.googleapis.com",
        api_key: str | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        super().__init__(
            base_url=base_url or "https://generativelanguage.googleapis.com",
            api_key=api_key,
            timeout_s=timeout_s,
        )

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "falta GEMINI_API_KEY"
        return True, ""

    def _headers(self) -> dict[str, str]:
        # La clave va por header: así no acaba en logs de URL ni en historial HTTP.
        return {"x-goog-api-key": self.api_key or "", "content-type": "application/json"}

    def _url(self, model: str, action: str = "generateContent") -> str:
        return f"{self.base_url}/v1beta/models/{model}:{action}"

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        if not self.api_key:
            raise ProviderError(ProviderErrorKind.NO_KEY, "sin GEMINI_API_KEY", provider=self.name)
        started = time.perf_counter()
        try:
            response = await self.client.post(
                self._url(request.model),
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
            model=request.model,
            usage=usage,
            latency_ms=(time.perf_counter() - started) * 1000,
            finish_reason=finish,
            raw={"usageMetadata": data.get("usageMetadata")},
        )
        result.cost_usd = self.estimate_cost(usage)
        return result
