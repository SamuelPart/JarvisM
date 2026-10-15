# JarvisM — Plan Maestro de Ingeniería

> Asistente/agente de voz multiplataforma (Linux · Windows · macOS) que entiende órdenes
> en lenguaje natural, controla el sistema operativo y las aplicaciones, y actúa de forma
> **proactiva** detectando problemas y sugiriendo mejoras.
>
> Versión del documento: `1.0` · Fecha: 2026-10-12 · Estado: **Aprobado para Fase 0–1**

---

## 0. Cómo leer este plan

| Documento | Qué contiene |
|---|---|
| **`PLAN.md`** (este) | Visión, principios, arquitectura de alto nivel, roadmap, KPIs, riesgos, costes |
| `docs/01-arquitectura.md` | Diseño técnico detallado, contratos entre capas, bucle del agente |
| `docs/02-roadmap.md` | Fases desglosadas con criterios de aceptación y tareas |
| `docs/03-seguridad-y-permisos.md` | Modelo de gobernanza, tiers de riesgo, threat model |
| `docs/04-guia-kali-linux.md` | **Cómo instalarlo y probarlo en tu Kali** paso a paso |
| `docs/05-proveedores-ia.md` | APIs, claves, modelos, router, costes y modo offline |
| `docs/06-backlog-ideas.md` | Catálogo de integraciones y mejoras que iremos sumando |
| `docs/adr/*` | Decisiones de arquitectura registradas (por qué elegimos X y no Y) |

Regla del proyecto: **ninguna línea de código nueva sin un ítem de fase que la justifique.**

---

## 1. Visión y definición del producto

### 1.1 En una frase
JarvisM es un **agente local-first** que vive en tu máquina: escucha, entiende, decide con un LLM,
ejecuta acciones sobre el SO a través de una capa de habilidades auditadas, y te habla.

### 1.2 Lo que NO es (límites explícitos)
- No es un chatbot en la nube: el cerebro orquestador corre **en tu equipo**.
- No es un keylogger ni un RAT: no hay servidor remoto, no hay telemetría saliente, todo es auditable.
- No ejecuta nada destructivo sin aprobación explícita (ver §5).
- No sustituye tu criterio en tareas de seguridad ofensiva: sugiere, tú autorizas.

### 1.3 Los tres modos de operación
1. **Modo reactivo (voz/texto)** — "Jarvis, abre Firefox y busca X", "¿cuánta RAM me queda?".
2. **Modo proactivo (watchdog)** — monitorea el sistema y *sugiere* cuando algo va mal:
   disco al 92 %, batería baja con procesos pesados, servicio caído, `apt` con 40 actualizaciones
   de seguridad pendientes, puerto expuesto, temperatura alta, un comando que falló 3 veces.
3. **Modo rutinas (programado)** — briefing matutino, resumen del día, limpieza semanal propuesta.

---

## 2. Principios de ingeniería (no negociables)

| # | Principio | Consecuencia práctica |
|---|---|---|
| P1 | **Local-first, privacidad por defecto** | STT/TTS/wake-word locales. A la nube solo sale texto, y es configurable a "solo local" (Ollama). |
| P2 | **El LLM propone, el policy engine dispone** | El modelo NUNCA ejecuta código. Emite *tool calls* tipados que pasan por validación de esquema + política de riesgo. |
| P3 | **Todo es un skill declarativo** | Añadir capacidad = añadir una clase con metadatos (nombre, esquema JSON, tier de riesgo, plataforma). Cero cambios en el core. |
| P4 | **Abstracción de plataforma** | `OSAdapter` con implementaciones Linux/Windows/macOS. El core no importa `subprocess` con comandos de un SO concreto. |
| P5 | **Degradación elegante** | Sin micrófono → modo texto. Sin API key → proveedor local/echo. Sin red → skills offline. El programa nunca se cae por una dependencia opcional ausente. |
| P6 | **Auditabilidad total** | Cada acción (propuesta, aprobada, ejecutada, resultado) queda en un log append-only con hash encadenado. |
| P7 | **Presupuesto explícito** | Tokens, dinero y tiempo de CPU con límites diarios configurables y kill-switch. |
| P8 | **Latencia es una feature** | Objetivo: de "dejo de hablar" a "empieza a responder" < 1.8 s (p50). Se mide en CI. |
| P9 | **Configuración por capas** | Defaults en código → `config.toml` → variables de entorno → flags CLI → perfil de usuario aprendido. |
| P10 | **Los modelos son datos, no código** | Ningún nombre de modelo hardcodeado. Todo vive en config para sobrevivir al churn de releases. |

---

## 3. Arquitectura de alto nivel

```
┌───────────────────────────────────────────────────────────────────────────┐
│  L7  OBSERVABILIDAD   audit log · métricas · tracing · reporte de costes   │
├───────────────────────────────────────────────────────────────────────────┤
│  L6  PRESENTACIÓN     TTS · TUI (Rich) · HUD overlay · panel web · bandeja │
├───────────────────────────────────────────────────────────────────────────┤
│  L5  EJECUCIÓN        Skill Registry → OSAdapter (linux/win/mac) → MCP     │
│      ┌──────────────────────────────────────────────────────────────┐     │
│      │ apps · archivos · sistema · red/web · shell guardado · media  │     │
│      │ clipboard · agenda · recordatorios · git · visión de pantalla │     │
│      └──────────────────────────────────────────────────────────────┘     │
├───────────────────────────────────────────────────────────────────────────┤
│  L4  GOBERNANZA       Policy Engine (tiers T0–T3) · Approval Gate ·        │
│                       Budget Guard · Rate Limiter · Kill Switch            │
├───────────────────────────────────────────────────────────────────────────┤
│  L3  COGNICIÓN        Router multi-LLM (Gemini/OpenAI/Anthropic/Ollama)    │
│                       Planner · Memoria (corta/larga/vectorial) · RAG      │
├───────────────────────────────────────────────────────────────────────────┤
│  L2  PERCEPCIÓN       VAD · Wake word · STT · NLU/intent · fusión de      │
│                       contexto (pantalla, ventana activa, clipboard)       │
├───────────────────────────────────────────────────────────────────────────┤
│  L1  ENTRADA          Micrófono · hotkey global · texto · CLI · REST/WS ·  │
│                       eventos del watchdog · scheduler                     │
├───────────────────────────────────────────────────────────────────────────┤
│  L0  SISTEMA          Linux (X11/Wayland, systemd, PulseAudio/PipeWire)    │
│                       Windows (Win32, PowerShell, DPAPI) · macOS (Cocoa)   │
└───────────────────────────────────────────────────────────────────────────┘
        Transversal: config/secrets · i18n (es/en) · plugins · tests · CI
```

### 3.1 El bucle del agente (una petición completa)

```
 ①DESPERTAR  wake word / hotkey / texto / evento del watchdog
      ↓
 ②CAPTURAR   VAD recorta silencio → audio 16 kHz mono
      ↓
 ③TRANSCRIBIR faster-whisper local (es) → texto + confianza
      ↓
 ④ENRIQUECER contexto: SO, ventana activa, clipboard, últimos eventos, memoria relevante
      ↓
 ⑤PLANIFICAR router elige modelo (barato para routing, grande para razonar)
             → el LLM devuelve: respuesta directa  O  tool_call[]
      ↓
 ⑥GOBERNAR   policy engine: ¿tier? ¿allowlist? ¿presupuesto? ¿rate limit?
             T0/T1 → auto · T2/T3 → pedir aprobación por voz/pantalla
      ↓
 ⑦EJECUTAR   skill → OSAdapter → resultado tipado (éxito/error/datos)
      ↓
 ⑧REFLEXIONAR si falló: reintentar con otra estrategia (máx. 2) o explicar al usuario
      ↓
 ⑨RESPONDER  TTS + TUI/HUD + notificación; si hay hallazgos → SUGERENCIAS
      ↓
 ⑩PERSISTIR  memoria de la sesión, audit log, métricas de coste/latencia
```

El bucle ⑤→⑦→⑧ es **iterativo** (agentic loop) con tope duro de N pasos por turno (default 6)
para evitar espirales de coste.

### 3.2 Stack tecnológico elegido

| Área | Elección principal | Alternativa / fallback | Por qué |
|---|---|---|---|
| Lenguaje del core | **Python 3.11+ (asyncio)** | TypeScript (Fase 6 UI) | Ecosistema IA/audio inigualable, multiplataforma, iteración rápida |
| Gestión de deps | **`uv`** + `pyproject.toml` | pip + venv | 10–50× más rápido, lockfile reproducible |
| HTTP a proveedores | **`httpx`** directo a REST | SDKs oficiales | Una sola dependencia, streaming uniforme, fallback trivial entre 4 proveedores (ADR-0001) |
| Config | **pydantic-settings** + TOML | YAML | Validación tipada en el arranque, errores legibles |
| CLI | **Typer** + **Rich** | argparse | Ergonomía y una TUI decente "gratis" |
| Wake word | **openWakeWord** (local, gratis) | Picovoice Porcupine (mejor, requiere cuenta) | 100 % offline, sin licencia |
| VAD | **Silero VAD** | webrtcvad | Precisión alta, modelo de ~1 MB |
| STT | **faster-whisper** (local) | Whisper API / Gemini STT | Privacidad + coste cero; `small`/`medium` en CPU va sobrado para es |
| TTS | **Piper** (local) | edge-tts (gratis online) · OpenAI TTS · ElevenLabs | Latencia <200 ms, voces en español, offline |
| LLM | Router: **Gemini Flash-Lite** (routing) + **Claude/GPT/Gemini Pro** (razonar) + **Ollama** (offline) | — | Coste/latencia/calidad por tarea (ADR-0003) |
| Persistencia | **SQLite** + `sqlite-vec` | Chroma / Qdrant | Cero infraestructura, un archivo, portable |
| API/UI remota | **FastAPI + WebSocket** | — | La misma API sirve a la TUI, al HUD y a futuras apps móviles |
| UI desktop (Fase 6) | **Tauri** (Rust + web) | Electron | Binario ~10 MB vs ~150 MB, menos RAM |
| Empaquetado | **PyInstaller/Nuitka** + instaladores por SO | `pipx`, contenedores | Usuario final sin Python |
| Calidad | **ruff** + **mypy** + **pytest** + **pre-commit** | — | Estilo y tipos obligatorios desde el día 1 |
| CI/CD | **GitHub Actions** (matriz 3 SO) | — | Binarios firmados en cada release |
| Integraciones | **MCP** (Model Context Protocol) | plugins propios | Estándar abierto: Jarvis es cliente *y* servidor MCP |

---

## 4. Roadmap ejecutivo

> Desglose completo con tareas y criterios de aceptación: **`docs/02-roadmap.md`**.

| Fase | Nombre | Entregable demostrable | Esfuerzo | Estado |
|---|---|---|---|---|
| **0** | Fundación | Repo, tooling, CI, config, `jarvis doctor` | 3–5 d | ✅ **hecha en este commit** |
| **1** | Núcleo conversacional multi-LLM | `jarvis chat` con router + fallback + memoria corta + streaming | 1–2 sem | 🟡 **esqueleto funcional** |
| **2** | Habilidades + gobernanza | `jarvis` abre apps, lee el sistema, busca archivos, shell guardado con aprobación | 2–3 sem | 🟡 **7 skills base** |
| **3** | Voz end-to-end | Wake word → STT → agente → TTS, modo manos libres, barge-in | 2–3 sem | ⬜ interfaces definidas |
| **4** | Proactividad | Watchdog con 12+ monitores y motor de sugerencias con cooldown | 2 sem | 🟡 **watchdog MVP** |
| **5** | Memoria y personalización | Recuerda preferencias, rutinas aprendidas, RAG sobre tus documentos | 2 sem | ⬜ |
| **6** | Presencia y apariencia | HUD overlay, bandeja del sistema, panel web, temas | 3–4 sem | ⬜ servidor FastAPI listo |
| **7** | Integraciones profundas | MCP, calendario, correo, navegador, domótica, git assistant | 3–4 sem | ⬜ |
| **8** | Distribución y hardening | Instaladores Win/mac/Linux, firma, autoupdate, i18n, accesibilidad | 2–3 sem | ⬜ scripts de instalación |

**Total estimado:** 18–24 semanas a ritmo part-time serio (10–15 h/sem) · 10–14 semanas full-time.
Cada fase termina en algo **demostrable**, no en código a medio hacer.

### Hitos de validación ("gates")
- **G1 (fin Fase 1):** conversación útil con ≥2 proveedores y failover automático demostrado apagando una clave.
- **G2 (fin Fase 2):** 20 órdenes de sistema distintas resueltas con éxito ≥90 %, cero acciones T3 sin approval.
- **G3 (fin Fase 3):** 10 comandos de voz seguidos en español con latencia p50 < 1.8 s y < 1 falso despertar/hora.
- **G4 (fin Fase 4):** el sistema detecta y *avisa* de 5 fallos reales inyectados en una semana de uso normal.
- **G5 (fin Fase 8):** un usuario sin conocimientos técnicos lo instala en < 10 min en los 3 SO.

---

## 5. Gobernanza de acciones (resumen — detalle en `docs/03-seguridad-y-permisos.md`)

Cada skill declara un **tier de riesgo**. El policy engine decide antes de ejecutar:

| Tier | Definición | Ejemplos | Comportamiento |
|---|---|---|---|
| **T0** | Lectura inocua, sin red | estado de disco, RAM, hora, lista de procesos | Auto + log |
| **T1** | Escritura reversible y local | crear nota, mover archivo a carpeta de Jarvis, ajustar volumen | Auto + log + undo disponible |
| **T2** | Irreversible local o salida a red | borrar archivo, instalar paquete, abrir URL, enviar correo | **Confirmación explícita** (voz o tecla) |
| **T3** | Peligroso / privilegiado / ofensivo | `sudo`, `rm -rf`, `dd`, `mkfs`, escaneo de red ajena, herramientas de Kali, volcar secretos | **Confirmación fuerte + allowlist + razón escrita en el audit log** |

Complementos obligatorios:
- **Denylist de patrones** (`rm -rf /`, `dd of=/dev/`, `:(){ :|:& };:`, `curl … | sh`, `chmod -R 777 /`).
- **Jaula de rutas**: escritura solo dentro de carpetas permitidas por config.
- **Presupuesto**: tokens/día, USD/día, nº de acciones/hora; al 80 % avisa, al 100 % se detiene.
- **Kill switch**: `Ctrl+C` doble, hotkey global, frase "Jarvis detente", y `jarvis kill` desde otra terminal.
- **Defensa contra prompt injection**: todo contenido externo (archivos, web, OCR, clipboard) entra
  etiquetado como `DATOS_NO_INSTRUCCIONES`; ningún dato puede elevar un tier ni saltarse el approval.

---

## 6. Proveedores de IA y estrategia de coste

Los precios cambian cada pocos meses, así que **los modelos viven en `config.toml`**, nunca en el código.
Valores orientativos de lista verificados en octubre de 2026
([comparativa de precios 2026](https://www.navyaai.com/guides/llm-api-pricing-comparison),
[precios de Gemini](https://ourcodeworld.com/articles/read/4598/google-gemini-api-pricing-2026-flash-pro-and-the-costs)):

| Rol en el router | Perfil | Candidatos (USD por M tokens, entrada/salida) |
|---|---|---|
| **Clasificador / routing** | baratísimo, <300 ms | Gemini Flash-Lite (~$0.10–0.30 / $0.40–2.50) · GPT-5.6 Luna ($0.20 / $1.20) |
| **Agente general** | bueno + tool calling fiable | Gemini Flash (~$0.75 / $3.75, promo hasta 31-dic-2026) · Claude Haiku 4.5 ($1 / $5) |
| **Razonamiento complejo** | calidad máxima | Claude Sonnet 5 ($2 / $10) · Gemini 3.1 Pro ($2 / $12) · GPT-5.6 Terra ($2 / $12) |
| **Offline / privado** | coste 0, sin red | Ollama: `qwen2.5:7b-instruct`, `llama3.1:8b` |

**Estrategia de ahorro (obligatoria desde Fase 1):**
1. *Cascade routing*: un modelo barato decide si la petición necesita al caro.
2. *Prompt caching* para el system prompt + descripción de skills (~80 % del input es estable).
3. *Caché semántica local* de respuestas repetidas ("¿qué hora es?", "estado del sistema").
4. *Skills deterministas antes que LLM*: si es una orden canónica ("abre firefox"), se resuelve por
   matcher local en ~5 ms y **sin gastar un solo token**. El LLM es el último recurso, no el primero.
5. *Tope de pasos agénticos* por turno y presupuesto diario duro.

**Tier gratuito para empezar sin tarjeta:** Gemini Flash/Flash-Lite en AI Studio, sin tarjeta de crédito,
con límites que Google ajusta sin aviso (del orden de 5–15 RPM y ~500–1500 peticiones/día según el modelo)
([límites del free tier](https://pecollective.com/tools/gemini-free-tier-guide/),
[estado del free tier en 2026](https://questloops.com/blog/how-to-use-google-gemini-for-free-in-2026-api-limits-explained)).
⚠️ En el free tier Google puede usar tu contenido para mejorar sus productos: **no lo uses con datos sensibles**;
para eso está el modo Ollama local.

**Presupuesto estimado de uso personal real** (200 interacciones/día, mezcla cascade): **3–15 USD/mes**.
Con Ollama local: **0 USD** a cambio de calidad inferior y más CPU/GPU.

---

## 7. Métricas de éxito (KPIs)

| KPI | Objetivo | Cómo se mide |
|---|---|---|
| Latencia fin-de-voz → inicio-de-respuesta | p50 < 1.8 s · p95 < 3.5 s | timestamps en el event bus |
| Precisión de intención (20 comandos canónicos) | > 92 % | suite de evaluación con corpus grabado |
| WER del STT en español | < 10 % (whisper `small`) | test sobre 50 frases grabadas |
| Falsos despertares del wake word | < 1 / hora | contador en el watchdog de audio |
| Acciones T3 ejecutadas sin approval | **0** (tolerancia cero) | assertion en tests + audit log |
| Coste diario | < 0.50 USD por defecto | budget guard |
| Cobertura de tests en `core/`, `safety/`, `skills/` | ≥ 85 % | pytest-cov en CI |
| Sugerencias proactivas aceptadas | > 40 % | feedback 👍/👎 en el HUD |
| Tiempo de instalación en SO limpio | < 10 min | smoke test en CI |

---

## 8. Riesgos y mitigaciones

| # | Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|---|
| R1 | El agente ejecuta algo destructivo | Media | **Crítico** | Tiers + denylist + jaula de rutas + approval + audit + tests de propiedad sobre el policy engine |
| R2 | Prompt injection vía archivo/web/pantalla | Alta | Alto | Etiquetado de datos no-instrucciones, validación de esquema, ningún dato puede cambiar tiers |
| R3 | Fuga de secretos al LLM | Media | Crítico | Redacción automática de patrones (API keys, tokens) antes de enviar; modo offline |
| R4 | Costes descontrolados | Alta | Medio | Cascade + caché + presupuesto duro + skills deterministas |
| R5 | Latencia que lo vuelve inutilizable | Media | Alto | Todo local por defecto; streaming de TTS por frases; prefetch del contexto |
| R6 | Dependencias de audio rotas en Linux (PortAudio/PipeWire) | Alta | Medio | Detección en `doctor`, guía por SO, modo texto como fallback permanente |
| R7 | Churn de modelos/precios de los proveedores | **Cierta** | Medio | Modelos en config, contrato `LLMProvider` estable, suite de compatibilidad por proveedor |
| R8 | Kali: el usuario tiene herramientas ofensivas al alcance | Media | Alto | Allowlist explícita de binarios, T3 por defecto para todo lo de `/usr/share/*`, aviso legal |
| R9 | Alcance desmedido (querer todo a la vez) | Alta | Alto | Gates de fase; nada de Fase N+1 sin cerrar N |
| R10 | Wayland bloquea atajos globales/captura | Media | Bajo | Backend X11 en Kali (XFCE), y portal XDG/`ydotool` donde haga falta |

---

## 9. Estructura del repositorio

```
JarvisM/
├── PLAN.md · README.md
├── pyproject.toml          # deps, extras [voice] [ui] [dev], entry point `jarvis`
├── .env.example            # plantilla de claves
├── .pre-commit-config.yaml # gitleaks + ruff + mypy + tests rápidos
├── jarvis/resources/
│   └── config.default.toml # configuración por defecto versionada (se distribuye con el paquete)
├── docs/                   # este plan + arquitectura + guías + ADRs
│   └── ci/ci.yml           # pipeline de CI listo para copiar a .github/workflows/
├── jarvis/
│   ├── cli.py              # Typer: chat · run · doctor · skills · audit · watch · serve
│   ├── config/             # settings (pydantic) + personas (prompts)
│   ├── core/               # orchestrator · router · matcher (N0) · memory · events
│   ├── providers/          # openai · anthropic · gemini · ollama · echo  (contrato común)
│   ├── skills/             # system_info · apps · files · web · desktop · shell (T3)
│   ├── platforms/          # OSAdapter: linux · windows · macos · factory
│   ├── safety/             # policy (tiers, denylist, budget) · audit (hash chain)
│   ├── proactive/          # watchdog (monitores) · suggester (motor de sugerencias)
│   ├── voice/              # audio · vad · wakeword · stt · tts   ← Fase 3
│   ├── server/             # FastAPI + WebSocket                  ← Fase 6
│   └── ui/                 # TUI Rich · HUD · panel web           ← Fase 6
├── scripts/                # install-kali.sh · install-macos.sh · install-windows.ps1 · jarvis.service
└── tests/                  # unit · integración · arquitectura · CLI
```

**Convenciones:** `ruff` (lint+format), `mypy --strict` en `core/` y `safety/`,
commits [Conventional Commits](https://www.conventionalcommits.org/), ramas `feat/*`, `fix/*`,
tests obligatorios para todo skill nuevo y para cualquier cambio en `safety/`.

---

## 10. Lo que necesito de ti (decisiones pendientes)

1. **Presupuesto de API**: ¿empezamos solo con el free tier de Gemini, o activas también claves de
   OpenAI/Anthropic desde el día 1? (Afecta al router por defecto.)
2. **Privacidad**: ¿aceptas que el audio/transcripciones pasen por la nube en Fase 3, o lo montamos
   100 % local desde el principio (más pesado en CPU pero cero fuga)?
3. **Idioma de la voz**: ¿español neutro, o con alguna variante regional?
4. **Prioridad de la Fase 2**: ¿qué te urge más — control de apps/ventanas, gestión de archivos,
   o el compañero de terminal que te sugiere comandos cuando algo falla?
5. **Hardware de tu Kali**: CPU/RAM/GPU. Define si whisper `small` o `medium`, y si Ollama es viable.

Mientras tanto, el MVP de las Fases 0–2 ya está en el repo y es ejecutable: mira
**`docs/04-guia-kali-linux.md`** para probarlo hoy mismo.

### Estado real en este commit (honestidad de ingeniería)

| Métrica | Valor medido |
|---|---|
| Habilidades registradas | **27** (15 T0 · 8 T1 · 3 T2 · 1 T3) |
| Cobertura del matcher local (N0) | **88 %** de un corpus de 24 órdenes canónicas, 0 tokens |
| Tests | **322** en ~4 s, sin red y sin tocar el sistema real |
| Cobertura | **67 %** global · `safety/policy` 92 % · `audit` 93 % · `orchestrator` 87 % · `matcher` 90 % |
| `ruff check` / `ruff format` / `mypy` | limpios (mypy estricto en `core/` y `safety/`) |
| Adapters | Linux probado a fondo · Windows/macOS implementados y con tests simulados, **sin verificar en hardware real** |

#### Revisión post-instalación (2026-10-12)

Bugs encontrados instalando el MVP en un Kali limpio (sin claves de API), es decir
en el primer arranque real del usuario, no en el portátil del desarrollador:

| Síntoma | Causa raíz | Arreglo | Regresión |
|---|---|---|---|
| `jarvis chat --provider echo` tardaba ~3 s e ignoraba el proveedor pedido | `Router.model_for()` hardcodeaba `ollama` al detectar entorno sin claves, pisando la cadena reordenada por la CLI | `_local_provider()` respeta `default_chain` y saca el modelo de `[router.fallback_models]` (P10) | `test_model_for_respects_pinned_echo` |
| Idem en modo privado (`privacy.offline`) | `ProviderRegistry.chain()` ignoraba `prefer` en la rama de offline estricto | `prefer` manda si es un proveedor local | `test_chain_honors_prefer_in_strict_offline` |
| Un demonio Ollama apagado costaba 2 reintentos (~3 s) antes del failover | `NETWORK` estaba en la tabla de reintentables y el "connection refused" caía dentro | `ProviderError.retryable` pasa a tri-estado (`None` = decídelo por el tipo) + `ConnectError` se marca no reintentable | `test_connection_refused_fails_over_without_backoff` |
| `pytest` no colectaba en una instalación limpia `--dev` | El extra `dev` no incluía las deps del servidor que usa `tests/test_server.py` | FastAPI/uvicorn/websockets añadidos a `dev` + `importorskip` antes del import | suite completa verde en clon nuevo |

Medido tras el arreglo: `--provider echo` responde en **14 ms** (antes ~3 s con
warnings) y `jarvis chat` sin claves en **67 ms**.

#### Revisión con claves reales (2026-10-14)

Primer uso real con clave de Gemini (`AQ.`) y de NVIDIA NIM. Los dos fallos más
graves del proyecto hasta la fecha salieron aquí:

| Síntoma | Causa raíz | Arreglo | Regresión |
|---|---|---|---|
| **Gemini fallaba el 100 % de los turnos de conversación** con `HTTP 400: Unknown name "additionalProperties"` | `parameters` de una `functionDeclaration` es un subconjunto de OpenAPI 3.0 y no admite `additionalProperties`, que **todas** las skills declaran (correctamente, para validar en local) | `sanitize_schema_for_gemini()`: limpia el esquema justo antes de enviarlo, **sin mutar el original**, y convierte `const`→`enum` y `type: [T,"null"]`→`nullable` | `test_gemini_schema.py` (8 tests, incluido uno que recorre las 27 skills reales) |
| Failover a NVIDIA = `HTTP 404 modelo inexistente` sin decir qué modelo | El mensaje de error no incluía el modelo, así que un 404 era indistinguible de "endpoint roto"; y el health check mandaba el modelo barato de **otro** proveedor | El modelo va en el log y en el error; `request_model_for_health()` usa `[router.fallback_models]`, la tabla donde vive el nombre de cada proveedor | `test_nvidia_provider.py` |
| `JARVIS__ROUTER__DEFAULT_CHAIN=gemini` (un solo proveedor) reventaba con `ValidationError` | `_coerce` solo convertía a lista las cadenas **con coma** | `_ConfigBase` normaliza cualquier `list[str]` en `mode="before"`, venga de donde venga | `test_settings.py` (5 tests) |
| `org/modelo` (IDs de NIM) se enrutaba a Ollama por contener "llama"/"qwen" | Heurística por subcadena sin distinguir namespaced de tag local | Regla: `/` y sin `:` → NVIDIA; `:` → Ollama | `test_model_name_routing` |
| `entra a google` iba al LLM (y con Gemini roto, acababa en eco) | El matcher solo resolvía URLs completas | Alias de sitios frecuentes + dominios sueltos en `_match_web` | `test_matcher.py` |

**NVIDIA NIM entra como proveedor de primera clase** (`jarvis/providers/nvidia_provider.py`):
OpenAI-compatible, gratis (~40 RPM, sin tope diario), 100+ modelos abiertos. Va
**segundo en la cascada** (`gemini → nvidia → anthropic → openai → ollama → echo`),
de modo que el relevo de Gemini también es gratis. Verificado con un servidor
Gemini falso que aplica la misma validación de esquemas que Google: el payload con
las 27 herramientas se acepta.
