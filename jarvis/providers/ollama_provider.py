"""Proveedor Ollama (LLM local, coste 0, sin red).

Usa el endpoint nativo /api/chat, que acepta el mismo formato `tools` que
OpenAI en las versiones recientes. Si el modelo no soporta tool calling, el
router lo degrada a "solo conversación" y las acciones las resuelve el matcher local.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

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
    messages: list[dict[str, Any]] = []
    for msg in request.messages:
        if msg.role == "tool":
            messages.append({"role": "tool", "content": msg.content})
            continue
        entry: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_calls:
            entry["tool_calls"] = [
                {"function": {"name": tc.skill, "arguments": tc.arguments}} for tc in msg.tool_calls
            ]
        messages.append(entry)
    payload: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": request.temperature, "num_predict": request.max_tokens},
    }
    if request.tools:
        payload["tools"] = [
            {
                "type": "function",
                "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
            }
            for t in request.tools
        ]
    payload.update(request.extra)
    return payload


def parse_response(data: dict[str, Any]) -> tuple[str, list[ToolCall], Usage]:
    message = data.get("message") or {}
    text = message.get("content") or ""
    calls: list[ToolCall] = []
    for raw in message.get("tool_calls") or []:
        fn = raw.get("function") or {}
        args = fn.get("arguments")
        parsed = args if isinstance(args, dict) else safe_json_loads(str(args or ""))
        calls.append(ToolCall(id=f"ollama_{len(calls)}", skill=fn.get("name", ""), arguments=parsed, raw=raw))
    usage = Usage(
        input_tokens=int(data.get("prompt_eval_count") or 0),
        output_tokens=int(data.get("eval_count") or 0),
    )
    return text, calls, usage


class OllamaProvider(LLMProvider):
    name = "ollama"
    supports_tools = True
    supports_vision = False
    supports_stream = True
    pricing = (0.0, 0.0)  # local: sin coste monetario

    def __init__(
        self, *, base_url: str = "http://127.0.0.1:11434", api_key: str | None = None, timeout_s: float = 60.0
    ) -> None:
        super().__init__(base_url=base_url or "http://127.0.0.1:11434", api_key=api_key, timeout_s=timeout_s)

    def available(self) -> tuple[bool, str]:
        # Ollama no necesita clave; solo que el demonio esté escuchando.
        return True, ""

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        started = time.perf_counter()
        try:
            response = await self.client.post(
                f"{self.base_url}/api/chat", json=build_payload(request), timeout=request.timeout_s
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Demonio apagado o puerto cerrado: reintentar contra lo mismo solo
            # gasta el backoff antes de saltar a echo (medido: ~3 s por turno).
            # Se marca no-retryable y el router hace failover inmediato.
            raise ProviderError(
                ProviderErrorKind.NETWORK,
                f"no se pudo conectar con Ollama en {self.base_url} ({exc}). "
                "¿Está activo? `ollama serve` / `systemctl start ollama`",
                provider=self.name,
                retryable=False,
            ) from exc
        except Exception as exc:
            # Timeout de lectura o error suelto del socket: eso sí puede ser un
            # hipo pasajero (modelo cargando en VRAM) y merece reintento.
            raise ProviderError(
                ProviderErrorKind.NETWORK,
                f"fallo de red con Ollama en {self.base_url} ({exc})",
                provider=self.name,
                retryable=True,
            ) from exc

        if response.status_code != 200:
            raise self.classify_status(response.status_code, self.name, response.text)

        data = response.json()
        text, calls, usage = parse_response(data)
        return CompletionResult(
            text=text,
            tool_calls=calls,
            provider=self.name,
            model=data.get("model", request.model),
            usage=usage,
            latency_ms=(time.perf_counter() - started) * 1000,
            finish_reason=data.get("done_reason") or "",
            cost_usd=0.0,
            raw={"done": data.get("done")},
        )

    async def list_models(self) -> list[str]:
        try:
            response = await self.client.get(f"{self.base_url}/api/tags", timeout=10.0)
            if response.status_code != 200:
                return []
            return [m.get("name", "") for m in response.json().get("models", [])]
        except Exception:
            return []
