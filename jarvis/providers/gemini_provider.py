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


#: Claves de JSON Schema que la API de Gemini NO acepta dentro de
#: `functionDeclarations[].parameters`. Google implementa un subconjunto de
#: OpenAPI 3.0 y rechaza el resto con HTTP 400: "Unknown name
#: \"additionalProperties\"". El caso real: TODAS las skills declaran
#: `additionalProperties: false` (que es lo correcto para OpenAI y para validar
#: los argumentos en local), así que Gemini fallaba en el 100 % de los turnos de
#: conversación con herramientas — es decir, siempre.
_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "additionalProperties",
        "$schema",
        "$id",
        "$comment",
        "$anchor",
        "$defs",
        "definitions",
        "patternProperties",
        "unevaluatedProperties",
        "propertyNames",
        "dependentRequired",
        "dependentSchemas",
        "dependencies",
        "if",
        "then",
        "else",
        "not",
        "examples",
    }
)

#: Claves cuyo valor es un esquema hijo (o una lista de ellos).
_SCHEMA_KEYS = frozenset({"items", "additionalItems", "contains"})
_SCHEMA_LIST_KEYS = frozenset({"anyOf", "allOf", "oneOf", "prefixItems"})


def sanitize_schema_for_gemini(schema: Any) -> Any:
    """Adapta un JSON Schema al subconjunto que acepta la API de Gemini.

    Recursivo y **no muta** el esquema original: la limpieza se hace justo antes
    de enviar, así el mismo esquema sigue validando los argumentos en local
    (que es donde tiene que ser estricto).

    Conversiones que hace, además de borrar lo no soportado:

    - `const: X` -> `enum: [X]` (Gemini no tiene `const`).
    - `type: ["string", "null"]` -> `type: "string"` + `nullable: true`
      (Gemini no acepta `type` como lista).
    """
    if isinstance(schema, list):
        return [sanitize_schema_for_gemini(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key, value in schema.items():
        if key in _UNSUPPORTED_SCHEMA_KEYS:
            continue
        if key == "const":
            out["enum"] = [value]
            continue
        if key == "type" and isinstance(value, list):
            non_null = [v for v in value if v != "null"]
            if "null" in value:
                out["nullable"] = True
            if len(non_null) == 1:
                out["type"] = non_null[0]
            # Con varios tipos reales Gemini no tiene equivalente: se omite
            # `type` en vez de inventarse un `anyOf` que puede no encajar.
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {name: sanitize_schema_for_gemini(sub) for name, sub in value.items()}
            continue
        if key in _SCHEMA_KEYS:
            out[key] = sanitize_schema_for_gemini(value)
            continue
        if key in _SCHEMA_LIST_KEYS and isinstance(value, list):
            out[key] = [sanitize_schema_for_gemini(item) for item in value]
            continue
        out[key] = value
    return out


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
                        # Limpio: los esquemas de las skills traen
                        # `additionalProperties` y Gemini responde 400 si lo ve.
                        "parameters": sanitize_schema_for_gemini(t.parameters),
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
