# JarvisM

**Asistente y agente de voz para tu sistema operativo.** Corre en tu máquina, entiende órdenes en
lenguaje natural, **hace** cosas en tu sistema operativo y tus aplicaciones, y te **avisa** cuando
algo va mal.

Linux · Windows · macOS · Python 3.10+

```bash
git clone https://github.com/SamuelPart/JarvisM.git && cd JarvisM
./scripts/install-kali.sh          # Linux   ·  install-macos.sh (macOS) · install-windows.ps1 (Windows)
source .venv/bin/activate
jarvis doctor                      # te dice exactamente qué falta y cómo arreglarlo
jarvis chat                        # empieza a hablarle
```

---

## Qué hace hoy (y qué hará)

| | Estado |
|---|---|
| 🗣️ **Voz**: wake word, STT y TTS locales (sin nube) | Interfaces definidas, implementación en **Fase 3** |
| 💬 **Conversación** con Gemini / OpenAI / Anthropic / Ollama y *failover* automático | ✅ Funcionando |
| 🖥️ **Control del sistema**: apps, ventanas, archivos, volumen, brillo, portapapeles, web | ✅ 27 habilidades |
| 🛡️ **Gobernanza**: 4 niveles de riesgo, denylist, jaula de rutas, aprobación humana, auditoría | ✅ Funcionando |
| 🔭 **Proactividad**: watchdog con 5 monitores y sugerencias accionables | ✅ MVP; se amplía en **Fase 4** |
| 🧠 **Memoria** de sesión y contexto | ✅ Básica; memoria semántica en **Fase 5** |
| ✨ **Apariencia**: HUD, bandeja del sistema, panel web | Esqueleto API listo; **Fase 6** |

Detalle completo, con criterios de aceptación por fase: **[docs/02-roadmap.md](docs/02-roadmap.md)**.

---

## Por qué este proyecto es distinto

Cualquier asistente con control del sistema es, técnicamente, un RAT. Lo que separa una herramienta
útil de un incidente son **cuatro decisiones de diseño** que aquí están en código, no en un README:

**1. El modelo no ejecuta nada.** El LLM solo puede emitir *tool calls* contra un catálogo cerrado de
27 habilidades con JSON Schema. Entre la propuesta y la ejecución hay un *policy engine* determinista
y testeado que puede permitir, exigir aprobación o denegar. ([ADR-0002](docs/adr/0002-llm-propone-policy-dispone.md))

**2. Cuatro niveles de riesgo.**

| Tier | Qué es | Comportamiento |
|---|---|---|
| **T0** | lectura inocua (estado, disco, procesos) | automático |
| **T1** | escritura reversible (volumen, notas, clipboard) | automático + `jarvis undo` |
| **T2** | irreversible o sale a internet (abrir web, cerrar ventana) | **te pregunta** |
| **T3** | privilegiado o destructivo (`sudo`, `nmap`, `dd`) | **confirmación escrita: "APRUEBO"** |

`rm -rf /`, `curl … | sh`, `dd of=/dev/sda` y 17 patrones más están **prohibidos siempre**, incluso con
`--yes` y aunque subas el umbral de auto-aprobación. Hay un test que lo verifica para todas las
configuraciones posibles.

**3. Todo queda auditado.** Cada turno, decisión de política, ejecución y aprobación va a un log
append-only con **cadena de hashes SHA-256**. `jarvis audit --verify` detecta cualquier edición.
Si alguien borra una fila, se enteran.

**4. Los datos externos no son órdenes.** Todo lo que viene de un archivo, una web, el OCR o el
portapapeles entra etiquetado como `DATOS_NO_INSTRUCCIONES`. Ningún dato puede subir un tier ni
saltarse una aprobación.

Y una decisión de coste: **el LLM es el último recurso**, no el primero. Un matcher determinista
resuelve el **88 %** de las órdenes frecuentes en ~5 ms y con **0 tokens**. ([ADR-0003](docs/adr/0003-cascade-routing.md))

---

## Ejemplos de uso

```bash
# Órdenes directas: resueltas sin gastar un token
jarvis chat --once "¿cuánta RAM me queda?"
jarvis chat --once "abre el navegador"
jarvis chat --once "qué procesos consumen más"
jarvis chat --once "sube el volumen al 40"
jarvis chat --once "busca los archivos *.pdf en ~/Documents"

# Conversación abierta: aquí sí entra el modelo
jarvis chat

# Ejecutar una habilidad suelta, con su nivel de riesgo a la vista
jarvis skills                       # catálogo completo
jarvis run system.disk
jarvis run shell.run command="df -h" reason="comprobar espacio"   # T3: pedirá APRUEBO
jarvis run shell.run command="ls -la" reason="listar" --dry-run   # solo simula

# Vigilancia proactiva
jarvis watch --interval 30

# Auditoría
jarvis audit --tail 20
jarvis audit --verify               # integridad de la cadena de hashes

# Coste
jarvis cost
```

---

## Seguridad: úsalo, no lo temas

```bash
jarvis doctor --security            # comprobaciones de seguridad del entorno
jarvis policy                       # resumen de la política activa
jarvis policy shell.run --explain command="ls" reason=x
```

- **Nunca lo ejecutes como root.** El instalador se niega y `doctor` te avisa si lo haces.
- **Redacción de secretos** antes de enviar nada a un proveedor (claves, tokens, PEM, JWT).
- **Rutas protegidas** (`~/.ssh`, `~/.gnupg`, `/etc/shadow`…) ni se leen ni se indexan.
- **Kill switch**: `/kill` en el chat, `jarvis --kill`, o el endpoint de la API.
- **Presupuesto duro**: 0,50 USD/día por defecto. Al agotarse, deja de llamar a la nube y sigue
  funcionando con el matcher local.
- **Modo offline real**: `jarvis chat --offline` fuerza Ollama + STT/TTS locales. Cero red.

Modelo de amenazas completo: **[docs/03-seguridad-y-permisos.md](docs/03-seguridad-y-permisos.md)**.

---

## Instalación

### Linux (Kali, Debian, Ubuntu, derivados)

```bash
sudo apt install -y python3-venv git
git clone https://github.com/SamuelPart/JarvisM.git && cd JarvisM
./scripts/install-kali.sh                 # --voice para audio, --ui para el HUD, --all para todo
source .venv/bin/activate
jarvis doctor
```

> **Kali y PEP 668:** nunca hagas `pip install` fuera del entorno virtual; Kali bloquea el Python
> del sistema a propósito. Todo va dentro de `.venv`.
>
> Guía paso a paso con un guion de pruebas completo: **[docs/04-guia-kali-linux.md](docs/04-guia-kali-linux.md)**.

### macOS

```bash
brew install python@3.12 git
git clone https://github.com/SamuelPart/JarvisM.git && cd JarvisM
./scripts/install-macos.sh
source .venv/bin/activate
jarvis doctor
```

Concede **Accesibilidad** y **Grabación de pantalla** a tu terminal en
*Ajustes del Sistema → Privacidad y seguridad* para que pueda controlar ventanas y micrófono.

### Windows 10/11

```powershell
winget install Python.Python.3.12 Git.Git
git clone https://github.com/SamuelPart/JarvisM.git; cd JarvisM
.\scripts\install-windows.ps1 -All
.\.venv\Scripts\Activate.ps1
jarvis doctor
```

Extras recomendados: `pip install pywin32` (control de ventanas) y `winget install nircmd`
o `pip install pycaw` (volumen).

### Dependencias de IA

Con **una** clave basta. La más fácil es Gemini, que es gratis y no pide tarjeta:

```bash
cp .env.example .env && chmod 600 .env
nano .env                     # pega GEMINI_API_KEY=...
jarvis doctor --providers     # health check real contra cada API
```

O **sin ninguna clave ni internet**, 100 % local:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b-instruct
jarvis chat --provider ollama
```

Sin clave y sin Ollama también funciona: `jarvis chat --provider echo` ejecuta órdenes directas
reales (estado del sistema, apps, archivos, hora) para que puedas probar toda la tubería.
Coste y estrategia de modelos: **[docs/05-proveedores-ia.md](docs/05-proveedores-ia.md)**.

---

## Cómo está construido

```
jarvis/
├── cli.py             Typer + Rich: chat, run, doctor, skills, policy, audit, watch, serve
├── config/            settings por capas (TOML→env→CLI) + personas y system prompt
├── core/              orquestador (bucle del agente) · router multi-LLM · matcher N0 · memoria
├── providers/         openai · anthropic · gemini · ollama · echo (contrato único sobre httpx)
├── skills/            27 habilidades declarativas con tier de riesgo y JSON Schema
├── platforms/         OSAdapter: linux · windows · macos (único sitio con subprocess)
├── safety/            policy engine (tiers, denylist, jaula, presupuesto) · audit con hash chain
├── proactive/         watchdog: monitores puros + cooldown + motor de sugerencias
├── voice/             Fase 3 (dependencias opcionales; sin ellas todo sigue funcionando)
├── server/            FastAPI + WebSocket para el HUD (Fase 6)
└── ui/                TUI, aprobación interactiva, badges de riesgo
```

**Cinco capas, contratos claros:** percepción → cognición → gobernanza → ejecución → presentación.
Cada capa se testea por separado inyectando dobles (`OSAdapter` falso, proveedor simulado), así que
la suite corre **sin tocar la red ni tu sistema real**. Arquitectura detallada:
**[docs/01-arquitectura.md](docs/01-arquitectura.md)**.

**Añadir una habilidad** = una clase con `name`, `description`, `parameters` (JSON Schema), `tier` y
`execute()`. Cero cambios en el core:

```python
class MySkill(Skill):
    name = "mio.hacer_algo"
    description = "Hace algo. Úsalo cuando el usuario pida X."
    parameters = {
        "type": "object",
        "properties": {"param": {"type": "string"}},
        "required": ["param"],
        "additionalProperties": False,
    }
    tier = RiskTier.T1
    undoable = True

    def execute(self, param: str) -> SkillResult:
        return SkillResult.success(f"Hecho: {param}")
```

---

## Desarrollo

```bash
pip install -e ".[dev]"
pytest -q                              # 278 tests en ~8 s, sin red y sin tocar tu sistema
pytest --cov=jarvis --cov-report=term
ruff check . && ruff format --check . && mypy jarvis
pre-commit install                     # o pre-commit run --all-files
```

La suite verifica, además de la funcionalidad, los **invariantes de arquitectura**
(`tests/test_architecture.py`):

- `subprocess` solo existe en `platforms/` y `skills/shell.py`.
- no hay `exec`, `eval` ni `os.system` en el core;
- ningún nombre de modelo está hardcodeado: todos viven en `config.default.toml`;
- no hay claves ni rutas de usuario en el código;
- las llamadas a APIs siempre son por HTTPS.

CI en matriz de 3 sistemas operativos + job específico de invariantes de seguridad +
instalación limpia desde los scripts reales. El pipeline está en **`docs/ci/ci.yml`**
(fuera de `.github/` a propósito, para que una integración sin permisos de `workflow`
no lo pierda): para activarlo, `mkdir -p .github/workflows && cp docs/ci/ci.yml .github/workflows/`

---

## Estado y honestidad sobre límites

Esto es un **MVP de las Fases 0–2**, no un producto terminado. Es honesto con lo que no hace:

- La **voz es Fase 3**: hoy se le habla por texto.
- El watchdog cubre disco, RAM, swap, carga, batería y temperatura. Faltan updates, servicios,
  red, logs SMART y caches (Fase 4).
- **macOS y Windows tienen adapters implementados pero sin verificar en hardware real** por el
  autor; en Linux está probado a fondo. Los tests de esos adapters se ejecutan en la matriz de CI,
  pero con datos simulados. Si encuentras algo, es un bug prioritario.
- La memoria es de sesión; la semántica con embeddings es Fase 5.
- El audio y el HUD no están implementados todavía.

Roadmap con lo que viene: **[docs/02-roadmap.md](docs/02-roadmap.md)** ·
Catálogo de mejoras priorizadas: **[docs/06-backlog-ideas.md](docs/06-backlog-ideas.md)**.

---

## Licencia

MIT. Úsalo sobre **sistemas propios o con autorización escrita explícita**. El proyecto no incluye
ni distribuye exploits, payloads ni credenciales, y las capacidades de red y escaneo quedan
desactivadas por defecto.
