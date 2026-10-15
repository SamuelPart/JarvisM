"""Proveedor NVIDIA NIM (build.nvidia.com).

NIM expone una API **OpenAI-compatible** (`/v1/chat/completions`), así que este
proveedor es una especialización de `OpenAIProvider`: cambia el nombre, el
endpoint por defecto y el nombre de la variable de entorno de la clave. Todo lo
demás (payload, parseo de tool calls, contabilidad de tokens) se reutiliza tal
cual, que es justo el motivo de que el contrato `LLMProvider` exista (ADR-0001).

Por qué merece un proveedor propio y no ir por el hueco de `openai`:

- El mensaje de error tiene que decir la verdad: "falta NVIDIA_API_KEY", no
  "falta OPENAI_API_KEY".
- La cuota es distinta (free tier ~40 RPM sin tope diario a fecha de oct-2026) y
  el catálogo son modelos abiertos tipo `deepseek-ai/deepseek-v3.2` o
  `meta/llama-4-scout-17b-16e-instruct`, con prefijo `org/modelo` — nombres que
  jamás deben mandarse a OpenAI.
- Aparece con su propio estado en `jarvis doctor --providers` y en las métricas
  del router, así que un fallo se diagnostica en un vistazo.
"""

from __future__ import annotations

from jarvis.providers.base import (
    CompletionRequest,
    CompletionResult,
    ProviderError,
    ProviderErrorKind,
)
from jarvis.providers.openai_provider import OpenAIProvider

#: Endpoint hospedado de NVIDIA. La clave se pide en https://build.nvidia.com
#: (cuenta gratuita de NVIDIA Developer Program, sin tarjeta).
DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"


class NvidiaProvider(OpenAIProvider):
    """OpenAI-compatible sobre NVIDIA NIM."""

    name = "nvidia"
    supports_tools = True
    # Depende del modelo elegido (hay NIM de visión), igual que en OpenAI.
    supports_vision = True
    supports_stream = True
    # Free tier: sin coste monetario. El presupuesto de tokens del router sigue
    # contando, así que un bucle descontrolado se frena igual.
    pricing = (0.0, 0.0)

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        api_key: str | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        super().__init__(base_url=base_url or DEFAULT_BASE_URL, api_key=api_key, timeout_s=timeout_s)

    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "falta NVIDIA_API_KEY"
        return True, ""

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        """Igual que OpenAI, pero con un mensaje de error honesto."""
        if not self.api_key:
            raise ProviderError(ProviderErrorKind.NO_KEY, "sin NVIDIA_API_KEY", provider=self.name)
        return await super().complete(request)
