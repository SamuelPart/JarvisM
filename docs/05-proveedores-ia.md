# 05 · Proveedores de IA, claves, router y costes

---

## 1. Dónde conseguir cada clave

| Proveedor | URL | Tarjeta | Notas |
|---|---|---|---|
| **Google Gemini** | https://aistudio.google.com/app/apikey | No (free tier) | El más fácil para empezar. Free tier solo en Flash/Flash-Lite |
| **OpenAI** | https://platform.openai.com/api-keys | Sí | Requiere saldo prepago; revisa el límite de gasto en el panel |
| **Anthropic** | https://console.anthropic.com/settings/keys | Sí | Tool calling muy fiable; ideal como "razonador" |
| **Ollama** (local) | https://ollama.com | No | `ollama pull qwen2.5:7b-instruct` — coste 0, sin red |
| Groq / OpenRouter / Mistral | respectivos paneles | Variable | El contrato `LLMProvider` los admite con ~40 líneas cada uno |

Almacena las claves en `.env` con `chmod 600`, o mejor en el **keyring del sistema**
(Secret Service en Linux, Keychain en macOS, DPAPI en Windows): `jarvis config set-key gemini`.

---

## 2. Precios orientativos (octubre 2026)

⚠️ Los precios y los nombres de modelo cambian cada pocos meses. **Estos valores son de referencia;
verifícalos en la página oficial antes de presupuestar.** Por eso en JarvisM ningún nombre de modelo
está hardcodeado: todos viven en `config.toml` (principio P10).

Fuentes consultadas: [comparativa multi-proveedor](https://www.navyaai.com/guides/llm-api-pricing-comparison),
[precios de OpenAI/Anthropic/Google/Grok](https://intuitionlabs.ai/articles/ai-api-pricing-comparison-grok-gemini-openai-claude),
[precios de Gemini 2026](https://ourcodeworld.com/articles/read/4598/google-gemini-api-pricing-2026-flash-pro-and-the-costs),
[tabla de 20+ modelos](https://www.clawrouters.com/blog/llm-api-pricing-guide-2026).

| Modelo (según se publica en oct-2026) | Entrada $/M | Salida $/M | Rol sugerido en JarvisM |
|---|---|---|---|
| Gemini 2.5 Flash-Lite | ~0.10 | ~0.40 | clasificador de intención, resúmenes, caché |
| Gemini Flash (3.6/3.7) | 0.75 *(promo hasta 31-dic-2026, luego 1.50)* | 3.75 | agente general con tool calling |
| GPT-5.6 Luna | 0.20 | 1.20 | clasificador barato |
| Claude Haiku 4.5 | 1.00 | 5.00 | agente general, respuestas rápidas |
| Gemini 3.1 Pro | 2.00 *(4.00 con >200k)* | 12.00 | razonamiento complejo, visión |
| Claude Sonnet 5 | 2.00 | 10.00 | **razonador principal**, planificación agéntica |
| GPT-5.6 Terra | 2.00 | 12.00 | razonador alternativo |
| Claude Opus 5 | 5.00 | 25.00 | solo tareas muy difíciles, bajo demanda |
| GPT-5.6 Sol | 5.00 *(4.00 promo hasta 21-nov-2026)* | 30.00 | solo tareas muy difíciles |
| Ollama `qwen2.5:7b` | 0 | 0 | modo offline/privado |

**Descuentos que sí importan a nuestro volumen:**
- *Prompt caching*: en Anthropic los aciertos de caché bajan a ~$0.10–0.50/M. Nuestro system prompt
  + descripciones de skills son ~2–4 k tokens **idénticos en cada turno** → cachearlos es dinero gratis.
- *Batch API* (~50 %): útil para los resúmenes nocturnos de memoria, que no tienen prisa.
- *Cuidado con el contexto largo*: varios proveedores **doblan** la tarifa por encima de 200k tokens.
  Nuestra ventana de memoria debe truncarse, no crecer indefinidamente.

---

## 3. El router

```
petición entrante
   │
   ├─► matcher local de órdenes canónicas ──► ¿resuelto? ──► SÍ → 0 tokens, ~5 ms ✅
   │                                                     └ NO ↓
   ├─► clasificador (modelo BARATO o embeddings locales)
   │      → categoría: chitchat · consulta_sistema · acción · razonamiento · visión
   │
   ├─► selección de modelo por categoría
   │      chitchat/consulta  → flash-lite / haiku / ollama
   │      acción (tool use)  → flash / haiku (tool calling fiable)
   │      razonamiento       → sonnet / pro / terra
   │      visión de pantalla → gemini pro / gpt visión
   │
   ├─► health check con caché 60 s + circuit breaker (3 fallos → 5 min fuera)
   ├─► envío con retry + backoff exponencial (429/5xx/timeouts)
   ├─► failover a la cadena configurada
   └─► contabilidad: tokens, coste estimado, latencia → event bus + budget guard
```

Configuración en `config.toml`:

```toml
[router]
default_chain = ["anthropic", "gemini", "openai", "ollama"]
routing_model = "cheap"          # perfil lógico, no un nombre concreto
max_steps_per_turn = 6
timeout_s = 30
max_rpm = 12                     # protege del 429 del free tier

[router.profiles]
cheap    = { provider = "gemini",    model = "gemini-2.5-flash-lite" }
general  = { provider = "gemini",    model = "gemini-3.7-flash" }
reasoner = { provider = "anthropic", model = "claude-sonnet-5" }
vision   = { provider = "gemini",    model = "gemini-3.1-pro" }
offline  = { provider = "ollama",    model = "qwen2.5:7b-instruct" }

[budget]
usd_per_day = 0.50
tokens_per_day = 2_000_000
warn_at_pct = 80
```

Los nombres anteriores son **ejemplos**: sustitúyelos por los que estén vigentes en tu cuenta
(`jarvis providers --list-models` consulta la lista real contra la API cuando el proveedor la expone).

---

## 4. Coste real esperado

Supuestos: 200 interacciones/día, 60 % resueltas por matcher local o modelo barato,
contexto medio de 1.500 tokens de entrada y 250 de salida.

| Escenario | Coste/día | Coste/mes |
|---|---|---|
| Free tier Gemini (con rate limits) | 0 USD | **0 USD** |
| Cascade con Flash-Lite + Haiku | ~0.05–0.15 USD | **1.5–5 USD** |
| Con razonador Sonnet/Pro en el 20 % de turnos | ~0.15–0.50 USD | **5–15 USD** |
| 100 % local (Ollama + whisper + Piper) | 0 USD | **0 USD** (solo electricidad) |
| Modo "todo frontier" (mala idea) | 3–10 USD | 90–300 USD ❌ |

El `budget.usd_per_day = 0.50` por defecto hace **imposible** el último escenario por accidente.

---

## 5. Modo offline / privado

```bash
jarvis --offline chat          # fuerza ollama + STT local + TTS local, corta toda red
```
Qué se pierde: calidad de razonamiento, visión de pantalla, y algunas integraciones.
Qué se gana: cero fugas, cero coste, funciona en un avión o en una red aislada de laboratorio.

Requisitos recomendados para offline decente: 16 GB RAM y, si puede ser, GPU con 6+ GB de VRAM.
En CPU pura, un 7B cuantizado responde en 2–8 s por turno: usable en texto, incómodo en voz.

---

## 6. Contratos de API que implementamos

Todos sobre `httpx.AsyncClient`, sin SDKs (ADR-0001):

| Proveedor | Endpoint | Formato de tool calling |
|---|---|---|
| OpenAI-compatible | `POST {base}/chat/completions` | `tools[].function` → `tool_calls[]` |
| Anthropic | `POST {base}/v1/messages` · header `anthropic-version: 2023-06-01` | `tools[].input_schema` → bloques `tool_use` / `tool_result` |
| Gemini | `POST {base}/v1beta/models/{model}:generateContent?key=…` | `tools[].functionDeclarations` → `functionCall` |
| Ollama | `POST {base}/api/chat` | compatible OpenAI (`tools`) en versiones recientes |
| Echo | — | ninguno (skills deterministas + respuestas planteadas en local) |

Cada proveedor implementa `health()`, `complete()`, `stream()` y `count_tokens_approx()`.
Los errores se normalizan a `ProviderError{kind: auth|rate_limit|timeout|server|network|model_not_found}`,
que es lo que consume el circuit breaker.
