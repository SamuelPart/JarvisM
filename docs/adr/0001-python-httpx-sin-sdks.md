# ADR-0001 · Python + httpx (sin SDKs oficiales) como núcleo

**Estado:** aceptado · **Fecha:** 2026-10-12

## Contexto
JarvisM necesita hablar con ≥4 proveedores de LLM (OpenAI, Anthropic, Gemini, Ollama) y además
con APIs de audio (STT/TTS) y del sistema operativo, en Linux, Windows y macOS. Las opciones eran:
(a) usar los SDK oficiales de cada proveedor, (b) un framework de agentes (LangChain/LlamaIndex),
(c) un cliente HTTP propio y delgado.

## Decisión
**Python 3.11+ con `httpx.AsyncClient` contra las APIs REST directamente.** Sin SDKs, sin framework.

## Justificación
1. **Dependencias:** cada SDK arrastra su propio árbol (anyio, distro, typing-extensions en
   versiones conflictivas). En Kali/Debian, donde el Python del sistema está protegido por PEP 668,
   cuanto menos árbol mejor. Un solo `httpx` cubre los cuatro proveedores.
2. **Failover uniforme:** el circuito de respaldo necesita tratar `429`, `401`, timeouts y errores de
   red de forma idéntica entre proveedores. Con SDKs hay que normalizar cuatro jerarquías de
   excepciones distintas; con HTTP hay una.
3. **Control de streaming:** queremos empezar el TTS con la primera frase terminada. Eso exige
   controlar el parsing SSE, y cada SDK lo expone de forma diferente.
4. **Sin framework de agentes:** LangChain añade 4 capas de abstracción entre nosotros y el HTTP,
   dificulta la auditoría (necesitamos el payload exacto en el audit log) y su API cambia cada mes.
   Nuestro bucle agéntico son ~200 líneas que entendemos al 100 %.
5. **Los SDKs siguen siendo bienvenidos como extra opcional** si algún proveedor añade una capacidad
   que no queramos reimplementar (p. ej. audio bidireccional en vivo).

## Consecuencias
- **A favor:** huella mínima, arranque rápido, tests con `httpx.MockTransport` sin red, un único
  punto donde añadir reintentos, métricas y redacción de secretos.
- **En contra:** hay que mantener la traducción de tool calling de cada proveedor a mano
  (3 formatos distintos). Se mitiga con `tests/providers/test_payloads.py`, que fija el payload
  esperado de cada uno; si un proveedor cambia la API, el test falla antes que el usuario.
- **Regla derivada:** ningún nombre de modelo se hardcodea. Todo vive en `config.toml` (P10),
  porque el churn de releases de modelos es altísimo.
