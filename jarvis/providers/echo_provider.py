"""Proveedor `echo`: sin red, sin clave, sin coste.

Su función es permitir probar TODA la tubería (CLI -> orquestador -> matcher ->
policy engine -> skill -> OSAdapter -> auditoría) antes de gastar un token, y
servir de último eslabón del failover cuando no hay ninguna clave configurada.

No inventa respuestas: dice claramente que está en modo local sin IA, y deja que
el matcher determinista resuelva las órdenes canónicas (ADR-0003, nivel N0).
"""

from __future__ import annotations

import time
from typing import Any

from jarvis.providers.base import (
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    Message,
    Usage,
)

OFFLINE_REPLY = (
    "Estoy en modo local sin modelo de IA conectado: puedo ejecutar las órdenes directas del "
    "catálogo (estado del sistema, apps, archivos, hora) y el watchdog sigue vigilando, pero no "
    "puedo mantener una conversación abierta. Configura una clave en `.env` (GEMINI_API_KEY es la "
    "más fácil, no pide tarjeta) o levanta Ollama para el modo 100% local."
)

_CHITCHAT = {
    ("hola", "buenas", "hey", "hi", "buenos días", "buenas tardes", "buenas noches"): (
        "A tus órdenes. Dime qué necesitas y lo reviso."
    ),
    ("gracias", "muchas gracias", "perfecto"): "Un placer. Sigo atento.",
    ("quién eres", "quien eres", "cómo te llamas", "como te llamas"): (
        "Soy Jarvis, tu asistente local. Corro en tu equipo y solo salgo a internet si tú lo configuras."
    ),
    ("ayuda", "help", "qué puedes hacer", "que puedes hacer"): (
        "Puedo consultar el estado del sistema, abrir aplicaciones, buscar archivos, abrir webs, "
        "gestionar el portapapeles y ejecutar comandos (estos últimos siempre con tu confirmación "
        "explícita). Escribe `jarvis skills` para ver el catálogo completo con su nivel de riesgo."
    ),
}


def offline_reply(messages: list[Message]) -> str:
    """Busca una respuesta canónica en el último mensaje; si no, contesta el aviso."""
    last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
    text = last_user.strip().lower().rstrip("?¡!.,;")
    for keys, reply in _CHITCHAT.items():
        if any(text == k or text.startswith(k) for k in keys):
            return reply
    return OFFLINE_REPLY


class EchoProvider(LLMProvider):
    name = "echo"
    supports_tools = False
    supports_vision = False
    supports_stream = True
    pricing = (0.0, 0.0)

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

    def available(self) -> tuple[bool, str]:
        return True, ""

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        started = time.perf_counter()
        text = offline_reply(request.messages)
        usage = Usage(input_tokens=request.prompt_tokens_estimate(), output_tokens=max(1, len(text) // 4))
        return CompletionResult(
            text=text,
            tool_calls=[],
            provider=self.name,
            model="echo-local",
            usage=usage,
            latency_ms=(time.perf_counter() - started) * 1000,
            finish_reason="stop",
            cost_usd=0.0,
        )
