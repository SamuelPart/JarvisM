# 01 · Arquitectura técnica detallada

Este documento baja a nivel de contrato lo que `PLAN.md` describe en alto nivel.

---

## 1. Mapa de procesos

JarvisM corre como **un solo proceso Python asyncio** con tareas cooperativas, más procesos
auxiliares opcionales:

```
jarvisd (proceso principal)
├── task: input_loop        ← CLI / WebSocket / hotkey / eventos del watchdog
├── task: audio_loop        ← VAD + wake word (solo Fase 3, thread aislado por GIL)
├── task: agent_loop        ← orquestador (perceive→plan→act→respond)
├── task: watchdog_loop     ← muestreo de monitores cada N s
├── task: scheduler_loop    ← rutinas (cron-like: briefing, resúmenes)
└── sync: FastAPI/uvicorn   ← opcional, `jarvis serve`

procesos externos (opcionales)
├── ollama serve            ← LLM local
└── piper / whisper.cpp     ← TTS/STT locales (invocados por subprocess o binding)
```

**Regla:** ninguna tarea bloquea el loop. Todo lo que sea CPU-bound (whisper, embeddings,
escaneo de disco) va a `asyncio.to_thread` o a un `ProcessPoolExecutor`.

---

## 2. Contratos entre capas

### 2.1 `LLMProvider` (proveedores)

```python
class LLMProvider(Protocol):
    name: str  # "openai" | "anthropic" | "gemini" | "ollama" | "echo"
    supports_tools: bool
    supports_vision: bool
    supports_stream: bool

    async def complete(self, req: CompletionRequest) -> CompletionResult: ...
    async def stream(self, req: CompletionRequest) -> AsyncIterator[Chunk]: ...
    async def health(self) -> ProviderHealth: ...  # barato, con caché de 60 s
```

`CompletionRequest` es **neutro**: `messages[]`, `tools[]`, `temperature`, `max_tokens`, `budget`.
Cada proveedor traduce a su formato (OpenAI `tools`/`tool_calls`, Anthropic `input_schema` +
bloques `tool_use`/`tool_result`, Gemini `functionDeclarations` + `functionCall`). Esa traducción
vive **solo** dentro del provider: el core nunca ve un payload específico.

Normalización crítica: los tres devuelven tool calls con formas distintas → todos se convierten a

```python
@dataclass
class ToolCall:
    id: str
    skill: str  # nombre registrado
    arguments: dict  # ya validado contra el JSON Schema del skill
    raw: dict  # payload original, para el audit log
```

### 2.2 `Skill` (habilidades)

```python
class Skill(ABC):
    name: str  # "apps.launch"
    description: str  # para el LLM: qué hace y cuándo usarla
    parameters: dict  # JSON Schema
    tier: RiskTier  # T0..T3
    platforms: set[Platform]  # dónde existe
    undoable: bool
    timeout: float

    async def run(self, ctx: SkillContext, **kwargs) -> SkillResult: ...
```

`SkillResult` = `{ok: bool, data: Any, message_for_user: str, message_for_llm: str, undo: Callable|None}`.
Separar `message_for_user` de `message_for_llm` evita que el modelo repita ruido interno en voz alta.

**El registro es descubrible:** `jarvis skills` lista nombre, tier, plataformas y parámetros.
El LLM recibe la descripción + esquema; nada más. Así el prompt no crece con la implementación.

### 2.3 `OSAdapter` (plataformas)

```python
class OSAdapter(ABC):
    platform: Platform

    # sistema
    def system_info(self) -> SystemInfo: ...
    def disk_usage(self) -> list[Volume]: ...
    def processes(self, top_n: int) -> list[Proc]: ...
    def battery(self) -> Battery | None: ...
    def temperatures(self) -> dict[str, float]: ...

    # aplicaciones y ventanas
    def list_apps(self) -> list[App]: ...
    def launch(self, app: str, args: list[str]) -> LaunchResult: ...
    def focus_window(self, title_pattern: str) -> bool: ...
    def active_window(self) -> WindowInfo | None: ...

    # entorno de escritorio
    def set_volume(self, pct: int) -> bool: ...
    def set_brightness(self, pct: int) -> bool: ...
    def notify(self, title: str, body: str, level: Level) -> bool: ...
    def clipboard_get(self) -> str: ...
    def clipboard_set(self, text: str) -> bool: ...

    # paquetes (solo lectura por defecto)
    def pending_updates(self) -> UpdateSummary: ...
```

| Capacidad | Linux | Windows | macOS |
|---|---|---|---|
| info de sistema | `/proc`, `psutil`, `lsb_release` | WMI/CIM, `psutil` | `sysctl`, `psutil` |
| lanzar apps | `.desktop` (XDG), `$PATH`, `gio launch` | Registro `App Paths`, `Start-Process`, UWP | `open -a`, `mdfind` |
| ventanas | `wmctrl`/`xdotool` (X11), portal XDG (Wayland) | `pywin32`/`GetForegroundWindow` | AppleScript/AXUIElement |
| volumen/brillo | `pactl`/`wpctl`, `brightnessctl` | `pycaw`, WMI brightness | `osascript`, `brightness` |
| notificaciones | `notify-send` (libnotify) | WinRT toast | `osascript display notification` |
| clipboard | `wl-paste`/`xclip` | `pyperclip`/Win32 | `pbcopy`/`pbpaste` |
| paquetes | `apt`/`dnf`/`pacman` | `winget` | `brew` |

Todo se resuelve por **detección en tiempo de ejecución** con `shutil.which` y fallbacks; si falta
una herramienta el adapter devuelve `Capability(unavailable, hint="instala wmctrl")` en vez de
explotar. `jarvis doctor` muestra la matriz de capacidades.

### 2.4 `PolicyEngine` (gobernanza)

```python
def evaluate(call: ToolCall, ctx: Context) -> Decision
# Decision = ALLOW | ALLOW_WITH_LOG | REQUIRE_APPROVAL(reason) | DENY(reason)
```

Orden de evaluación (corto-circuito):
1. Kill switch activo → `DENY`.
2. Skill no registrado / no disponible en esta plataforma → `DENY`.
3. Validación de argumentos contra JSON Schema → `DENY` si no pasa.
4. Denylist de patrones sobre los argumentos → `DENY` (T3 siempre).
5. Jaula de rutas: cualquier path fuera de las raíces permitidas → eleva a T2/T3.
6. Budget guard: ¿quedan tokens/USD/acciones? → `DENY` si se agotó.
7. Rate limiter: ventana deslizante por skill → `REQUIRE_APPROVAL` si se excede.
8. Tier del skill + reglas del usuario (`policy.toml`) → decisión final.

**Propiedad invariante testeada:** *un tier nunca puede bajar por información proveniente de datos
externos*. Solo la config del usuario y el código la definen.

### 2.5 Memoria

```
Memoria de trabajo (turno)     → lista de mensajes, se trunca con ventana deslizante
Memoria de sesión (horas)      → SQLite, resume al cerrar con un LLM barato
Memoria episódica (días/semanas)→ resúmenes jerárquicos + embeddings en sqlite-vec
Memoria semántica/perfil        → hechos estables: "usuario prefiere firefox", "proyecto X en ~/dev"
Memoria procedimental           → macros aprendidas: secuencias de skills que el usuario repite
```

Escritura en memoria semántica = **T1** (reversible: `jarvis memory forget`).
Nunca se guardan secretos: filtro de redacción antes de persistir.

---

## 3. Event bus interno

Todo lo interesante emite un evento tipado; la UI y el observador solo leen eventos.

```
wake.detected · audio.speech_end · stt.transcript {text, confidence, ms}
context.enriched {window, clipboard_digest, system_digest}
llm.request {provider, model, tokens_est} · llm.response {tokens, cost, ms}
tool.proposed {skill, args, tier} · policy.decision {decision, reason}
approval.requested · approval.granted | approval.denied
tool.result {skill, ok, ms} · agent.step {n, action} · turn.completed {ms, cost}
suggestion.emitted {id, kind, severity} · suggestion.feedback {id, accepted}
budget.threshold {pct} · watchdog.alert {monitor, value}
```

Beneficios: trazas completas gratis, la TUI/HUD es un consumidor más, y los tests se hacen
suscribiéndose a eventos en vez de mockear medio sistema.

---

## 4. Flujo de una sugerencia proactiva

```
monitor (disco 92%) → umbral cruzado → deduplicador (misma alerta, cooldown 6h)
   → generador de sugerencia (regla determinista primero, LLM solo si hace falta redacción)
   → filtro de pertinencia (¿modo no-molestar? ¿usuario en una videollamada? ¿focus?)
   → priorización (severity × confianza × recencia)
   → entrega: notificación del SO + línea en el HUD + voz SOLO si severity ≥ alta
   → feedback 👍/👎 → ajusta pesos (aprendido simple, sin LLM)
```

Las sugerencias **nunca ejecutan**: proponen un `ToolCall` pre-cargado que el usuario aprueba.
Ejemplo real: *"Disco al 92 %. Los 4,1 GB de `~/.cache/pip` y 2,8 GB de imágenes Docker huérfanas
se pueden limpiar. ¿Ejecuto `pip cache purge` y `docker image prune`?"* → eso es T2, pide confirmación.

---

## 5. Decisiones de rendimiento

| Cuello de botella | Técnica |
|---|---|
| STT lento | whisper `small` cuantizado int8 + streaming parcial; solo el último segmento va al LLM |
| LLM lento | Streaming de tokens → TTS por frases (empieza a hablar con la 1ª frase terminada) |
| Prompt enorme | Descripciones de skills comprimidas; solo se incluyen los skills candidatos tras un matcher local |
| Matcher local | Expresiones + embeddings ligeros resuelven órdenes canónicas sin llamar al LLM (0 tokens, ~5 ms) |
| Contexto del SO | Caché de 2–5 s para `system_info`, `active_window`, `list_apps` |
| Arranque en frío | Lazy imports de audio/ML; el CLI debe arrancar < 300 ms sin extras instalados |

---

## 6. Extensibilidad

Tres mecanismos, de menor a mayor potencia:
1. **Skills de usuario**: carpeta `~/.config/jarvis/skills/*.py` se auto-descubre al arrancar
   (con aviso explícito en el log: "cargando skill de terceros X").
2. **Cliente MCP**: conectar servidores MCP externos (GitHub, Notion, Home Assistant, Playwright…)
   → sus herramientas aparecen como skills con tier T2 por defecto.
3. **Servidor MCP**: exponer JarvisM como servidor para que otras apps le den órdenes.

Los plugins de terceros arrancan con tier **mínimo T2** y no pueden registrar skills T0.
