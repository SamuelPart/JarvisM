"""Contratos y utilidades de los proveedores de LLM (ADR-0001).

Un único modelo de datos neutro; cada proveedor traduce a su dialecto y
devuelve el mismo `CompletionResult`. Así el router puede conmutar entre
OpenAI, Anthropic, Gemini y Ollama sin que el core se entere.
"""

from __future__ import annotations

import enum
import json
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class ToolSpec:
    """Descripción de un skill tal y como la ve el modelo."""

    name: str
    description: str
    parameters: dict[str, Any]

    def token_estimate(self) -> int:
        return max(1, len(self.description) // 3 + len(json.dumps(self.parameters)) // 4)


@dataclass(slots=True)
class Message:
    role: Role
    content: str = ""
    name: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str | None = None

    def to_openai(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.skill, "arguments": json.dumps(tc.arguments, ensure_ascii=False)},
                }
                for tc in self.tool_calls
            ]
        if self.role == "tool":
            msg["tool_call_id"] = self.tool_call_id or ""
        if self.name and self.role != "tool":
            msg["name"] = self.name
        return msg

    def to_anthropic(self) -> dict[str, Any]:
        blocks: list[dict[str, Any]] = []
        if self.content:
            blocks.append({"type": "text", "text": self.content})
        for tc in self.tool_calls:
            blocks.append({"type": "tool_use", "id": tc.id, "name": tc.skill, "input": tc.arguments})
        if self.role == "tool":
            blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": self.tool_call_id or "",
                    "content": self.content,
                }
            ]
        # En Anthropic el resultado de una herramienta viaja como rol `user`
        # con un bloque `tool_result`; solo el assistant produce bloques tool_use.
        return {"role": "assistant" if self.role == "assistant" else "user", "content": blocks}


@dataclass(slots=True)
class ToolCall:
    """Petición normalizada de ejecución de un skill."""

    id: str
    skill: str
    arguments: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(slots=True)
class CompletionResult:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    latency_ms: float = 0.0
    finish_reason: str = ""
    cost_usd: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def wants_tool(self) -> bool:
        return bool(self.tool_calls)


class ProviderErrorKind(str, enum.Enum):
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    SERVER = "server"
    NETWORK = "network"
    MODEL_NOT_FOUND = "model_not_found"
    BAD_REQUEST = "bad_request"
    UNKNOWN = "unknown"
    NO_KEY = "no_key"


#: Tipos de error que merecen reintento cuando el proveedor no dice lo contrario.
#: Un `retryable` explícito en el `ProviderError` siempre gana sobre esta tabla.
RETRYABLE_KINDS = frozenset(
    {
        ProviderErrorKind.RATE_LIMIT,
        ProviderErrorKind.SERVER,
        ProviderErrorKind.TIMEOUT,
        ProviderErrorKind.NETWORK,
    }
)


class ProviderError(Exception):
    """Error normalizado. Es lo único que consume el circuit breaker.

    `retryable` es tri-estado a propósito: `None` significa "decídelo por el tipo
    de error" (tabla `RETRYABLE_KINDS`) y `True`/`False` significa "el proveedor
    sabe algo que el tipo no captura". El caso real que motivó esto es el
    "connection refused": es kind=NETWORK (retryable en teoría) pero reintentar
    contra un demonio que no está escuchando solo gasta el backoff antes de
    hacer failover (medido: ~3 s por turno con Ollama apagado).
    """

    def __init__(
        self,
        kind: ProviderErrorKind,
        message: str,
        *,
        provider: str = "",
        status: int = 0,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(f"[{provider or '?'}] {kind.value}: {message}")
        self.kind = kind
        self.provider = provider
        self.status = status
        self.retryable = retryable

    @property
    def should_retry(self) -> bool:
        """¿Reintentar en el MISMO proveedor antes de saltar al siguiente?"""
        if self.retryable is not None:
            return self.retryable
        return self.kind in RETRYABLE_KINDS


@dataclass(slots=True)
class CompletionRequest:
    messages: list[Message]
    model: str
    provider: str = ""
    tools: list[ToolSpec] = field(default_factory=list)
    temperature: float = 0.3
    max_tokens: int = 1024
    stream: bool = False
    timeout_s: float = 30.0
    extra: dict[str, Any] = field(default_factory=dict)

    def prompt_tokens_estimate(self) -> int:
        chars = sum(len(m.content) for m in self.messages)
        chars += sum(t.token_estimate() for t in self.tools)
        return max(1, chars // 4)


@dataclass(slots=True)
class Chunk:
    delta: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    done: bool = False
    result: CompletionResult | None = None


@dataclass(slots=True)
class ProviderHealth:
    name: str
    ok: bool
    reason: str = ""
    latency_ms: float = 0.0
    checked_at: float = field(default_factory=time.time)
    has_key: bool = True


class LLMProvider:
    """Contrato común. Cada implementación traduce a su dialecto REST."""

    name: str = "base"
    supports_tools: bool = False
    supports_vision: bool = False
    supports_stream: bool = True
    #: USD por millón de tokens, para la contabilidad del budget guard.
    pricing: tuple[float, float] = (0.0, 0.0)

    def __init__(self, *, base_url: str = "", api_key: str | None = None, timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self._client: Any = None

    # -- ciclo de vida ---------------------------------------------------- #
    @property
    def client(self) -> Any:
        if self._client is None:
            import httpx

            self._client = httpx.AsyncClient(timeout=self.timeout_s)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- API pública ------------------------------------------------------ #
    def available(self) -> tuple[bool, str]:
        """¿Puede usarse este proveedor ahora mismo? (sin llamadas de red)"""
        return True, ""

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        raise NotImplementedError

    async def stream(self, request: CompletionRequest) -> AsyncIterator[Chunk]:  # pragma: no cover
        result = await self.complete(request)
        yield Chunk(delta=result.text, tool_calls=result.tool_calls, done=True, result=result)

    async def health(self) -> ProviderHealth:
        start = time.perf_counter()
        try:
            available, reason = self.available()
            if not available:
                return ProviderHealth(self.name, False, reason, has_key=False)
            result = await self.complete(
                CompletionRequest(
                    messages=[Message(role="user", content="ping")],
                    model=request_model_for_health(self),
                    max_tokens=4,
                    timeout_s=10.0,
                )
            )
            return (
                ProviderHealth(self.name, True, "ok", (time.perf_counter() - start) * 1000, has_key=True)
                if result
                else ProviderHealth(self.name, False, "respuesta vacía")
            )
        except ProviderError as exc:
            return ProviderHealth(
                self.name, False, f"{exc.kind.value}: {exc}", has_key=exc.kind != ProviderErrorKind.NO_KEY
            )
        except Exception as exc:
            return ProviderHealth(self.name, False, f"error inesperado: {exc}")

    # -- utilidades ------------------------------------------------------- #
    def estimate_cost(self, usage: Usage) -> float:
        in_usd, out_usd = self.pricing
        return (usage.input_tokens * in_usd + usage.output_tokens * out_usd) / 1_000_000

    @staticmethod
    def classify_status(status: int, provider: str, body: str = "") -> ProviderError:
        """Convierte un HTTP status en el error normalizado correspondiente."""
        low = body.lower()
        if status in (401, 403):
            return ProviderError(
                ProviderErrorKind.AUTH,
                f"HTTP {status}: clave inválida o sin permisos",
                provider=provider,
                status=status,
            )
        if status == 404 or "not found" in low or "does not exist" in low:
            return ProviderError(
                ProviderErrorKind.MODEL_NOT_FOUND,
                f"HTTP {status}: modelo o ruta inexistente",
                provider=provider,
                status=status,
            )
        if status == 429:
            return ProviderError(
                ProviderErrorKind.RATE_LIMIT,
                "HTTP 429: rate limit / cuota agotada",
                provider=provider,
                status=status,
                retryable=True,
            )
        if 400 <= status < 500:
            return ProviderError(
                ProviderErrorKind.BAD_REQUEST,
                f"HTTP {status}: {body[:300]}",
                provider=provider,
                status=status,
            )
        if status >= 500:
            return ProviderError(
                ProviderErrorKind.SERVER,
                f"HTTP {status}: error del proveedor",
                provider=provider,
                status=status,
                retryable=True,
            )
        return ProviderError(ProviderErrorKind.UNKNOWN, f"HTTP {status}", provider=provider, status=status)


def request_model_for_health(provider: LLMProvider) -> str:
    """Modelo por defecto para el health check: uno que ESE proveedor conozca.

    Antes se usaba `model_cheap` para todos, así que el ping a NVIDIA iba con un
    modelo de Gemini y volvía un 404 que parecía "proveedor caído". Ahora se usa
    el modelo configurado en `[router.fallback_models]` para ese proveedor, que
    es exactamente la tabla donde vive el nombre de modelo de cada uno (P10).
    """
    from jarvis.config.settings import get_settings

    settings = get_settings()
    if provider.name == "ollama":
        return settings.router.model_offline
    return settings.router.fallback_models.get(provider.name) or settings.router.model_cheap


def safe_json_loads(text: str) -> dict[str, Any]:
    """Los modelos a veces envuelven el JSON en ```json ... ```. Lo toleramos."""
    if not text:
        return {}
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.split("```", 2)[1] if candidate.count("```") >= 2 else candidate.strip("`")
        if candidate.startswith("json"):
            candidate = candidate[4:]
    candidate = candidate.strip()
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else {"value": data}
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                pass
    return {}
