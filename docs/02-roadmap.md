# 02 · Roadmap detallado por fases

Cada fase tiene: objetivo, tareas, entregable, **criterios de aceptación** (lo que hay que poder
demostrar para darla por cerrada) y definición de "hecho".

Convención: una tarea es `[ ]` pendiente, `[~]` en curso, `[x]` hecha.

---

## Fase 0 · Fundación — ✅ completada

**Objetivo:** que el proyecto sea reproducible, verificable y agradable de desarrollar desde el día 1.

- [x] Estructura de paquetes `jarvis/` con `pyproject.toml` y extras opcionales
- [x] `ruff` + `mypy` + `pytest` configurados; `pre-commit` disponible
- [x] `.gitignore`, `.env.example`, `config.toml` versionado
- [x] Configuración tipada por capas (defaults → TOML → env → CLI) con `pydantic-settings`
- [x] `jarvis doctor`: diagnóstico de SO, Python, dependencias, claves, capacidades de plataforma
- [x] Audit log append-only con cadena de hashes
- [x] Scripts de instalación para Kali/Debian, macOS y Windows
- [x] Documentación: plan, arquitectura, seguridad, guía Kali, proveedores, backlog

**Aceptación:** `pip install -e .` en un entorno limpio y `jarvis doctor` salen verdes sin claves de API.

---

## Fase 1 · Núcleo conversacional multi-LLM — 🟡 esqueleto funcional

**Objetivo:** hablar con Jarvis por texto, con router entre proveedores y failover real.

- [x] Contrato `LLMProvider` + registro
- [x] Proveedores sobre `httpx`: OpenAI, Anthropic, Gemini, Ollama, Echo (offline)
- [x] Router con prioridad, salud, failover y balanceo por rol (barato/caro)
- [x] Normalización de tool calls entre los 3 formatos
- [x] Memoria de trabajo con truncado por tokens + memoria de sesión en SQLite
- [x] CLI `jarvis chat` con streaming y TUI Rich
- [x] Persona JARVIS configurable (idioma, tono, verbosidad)
- [ ] **Streaming real en el CLI** (hoy la respuesta llega completa)
- [ ] **Caché semántica** de respuestas repetidas
- [ ] **Cascade routing**: modelo barato decide si hace falta el caro
- [ ] **Redacción de secretos** antes de enviar cualquier texto a un proveedor
- [ ] Contador de coste acumulado visible en la TUI + `jarvis cost`
- [ ] Suite de evaluación de 50 prompts con respuestas esperadas (regresión de calidad)

**Aceptación (G1):**
1. Conversación fluida en español con contexto de ≥10 turnos.
2. Al invalidar la clave del proveedor primario, la siguiente petición **falla hacia el secundario
   sin que el usuario pierda el turno** y se informa del cambio.
3. `jarvis cost --today` cuadra con el consumo real del panel del proveedor (±10 %).
4. Con `--provider echo` o sin red, el CLI sigue funcionando (degradación elegante).

---

## Fase 2 · Habilidades + gobernanza — 🟡 7 skills base

**Objetivo:** que Jarvis haga cosas en tu sistema, con control total.

- [x] `Skill` ABC + registro + validación JSON Schema
- [x] Policy engine con tiers T0–T3, denylist, jaula de rutas, rate limit, budget
- [x] Approval gate en CLI (confirmación por teclado con timeout configurable)
- [x] Skills: `system.info`, `system.processes`, `system.disk`, `apps.list`, `apps.launch`,
      `files.search`, `files.open`, `web.open`, `shell.run` (T3), `clipboard.get/set`, `time.now`
- [x] `OSAdapter` Linux completo + Windows/macOS con detección y fallbacks
- [ ] Skills de escritorio: `windows.focus`, `windows.list`, `windows.close`, workspaces
- [ ] Skills de media: `media.volume`, `media.brightness`, `media.playback` (playerctl/MPD)
- [ ] Skill `system.update_check` (T0) y `system.updates_apply` (T3)
- [ ] Skill `system.screenshot` + `vision.describe_screen` (Gemini/GPT visión)
- [ ] Skill `git.status` / `git.summary` / `git.pr` (T2)
- [ ] Skill `notes.create` / `notes.search` (memoria persistente del usuario)
- [ ] **Undo**: cada skill T1/T2 registra su inverso; `jarvis undo` revierte la última acción
- [ ] **Dry-run**: `--dry-run` global que muestra qué se ejecutaría sin tocar nada
- [ ] Matcher local de órdenes canónicas (resolver sin LLM)
- [ ] Tests de propiedad sobre el policy engine (hypothesis): ningún input atraviesa T3 sin approval
- [ ] `jarvis audit --tail` y `jarvis audit --verify` (integridad de la cadena de hashes)

**Aceptación (G2):** 20 órdenes distintas en lenguaje natural resueltas con ≥90 % de éxito;
cero acciones T3 sin aprobación; `jarvis audit --verify` íntegro; todo skill nuevo trae test.

---

## Fase 3 · Voz end-to-end — ⬜

**Objetivo:** hablarle sin teclado, con latencia de conversación.

- [ ] Captura de audio multiplataforma (PortAudio/sounddevice, WASAPI, CoreAudio) + `jarvis audio test`
- [ ] VAD (Silero) para cortar por silencio en vez de por tiempo fijo
- [ ] Wake word: openWakeWord con modelo personalizado "jarvis" + Porcupine como opción premium
- [ ] STT local faster-whisper (`small` es por defecto, `medium` si hay GPU) con hipótesis parciales
- [ ] STT en la nube como fallback opcional (Whisper API / Gemini)
- [ ] TTS: Piper (voz es) con streaming por frases; edge-tts y OpenAI TTS como alternativas
- [ ] **Barge-in**: si el usuario habla mientras Jarvis responde, se corta el TTS al instante
- [ ] Confirmación por voz para approvals T2/T3 ("sí, adelante" / "no")
- [ ] Corrección: "no, quise decir X" re-procesa el último turno
- [ ] Métricas de latencia por etapa (VAD/STT/LLM/TTS) expuestas en `jarvis bench`
- [ ] Modo manos libres continuo con timeout de inactividad y aviso visual de "escuchando"

**Aceptación (G3):** 10 comandos seguidos en español, p50 < 1.8 s, < 1 falso despertar/hora en
una habitación con ruido normal, y el barge-in corta el audio en < 200 ms.

---

## Fase 4 · Proactividad y telemetría local — 🟡 watchdog MVP

**Objetivo:** que Jarvis avise antes de que el problema te rompa el día.

- [x] Loop de watchdog con monitores e intervalos configurables
- [x] Monitores: disco, RAM, swap, carga, batería, temperatura, procesos top, uptime
- [ ] Monitor de actualizaciones de seguridad pendientes (`apt`/`winget`/`brew`)
- [ ] Monitor de servicios fallidos (`systemctl --failed`, servicios de Windows)
- [ ] Monitor de red: puertos escuchando nuevos, interfaces en modo promiscuo, caídas
- [ ] Monitor de logs: errores nuevos en `journalctl -p err`, `dmesg`, Event Log
- [ ] Monitor de espacio en Docker/pip/npm caches y huérfanos limpiables
- [ ] Monitor de salud de discos (SMART) y de temperatura de GPU
- [ ] Monitor de "comando fallido repetido" integrado con el shell (hook `preexec`)
- [ ] Motor de sugerencias: deduplicador + cooldown + priorización + modo no-molestar
- [ ] Feedback 👍/👎 que ajusta pesos; `jarvis suggestions` lista el historial
- [ ] Reglas del usuario en TOML: umbrales, horas silenciosas, monitores activos
- [ ] Briefing matutino y resumen nocturno (scheduler)

**Aceptación (G4):** con 5 fallos inyectados a propósito (disco lleno, servicio caído, batería baja,
update de seguridad, puerto abierto), Jarvis avisa de los 5 sin spam (< 3 avisos duplicados/día).

---

## Fase 5 · Memoria y personalización — ⬜

- [ ] Embeddings locales (sentence-transformers o API) + `sqlite-vec`
- [ ] Resúmenes jerárquicos: turno → sesión → día → semana
- [ ] Perfil de usuario: apps favoritas, rutas de proyectos, horarios, tono preferido
- [ ] RAG opt-in sobre carpetas elegidas (con indexado incremental y respeto a `.gitignore`/secretos)
- [ ] Aprendizaje de macros procedimentales ("cada vez que digo X, haz A→B→C")
- [ ] `jarvis memory list|forget|export` + cifrado en reposo opcional
- [ ] Olvido programado (retention) y exclusión de categorías sensibles

**Aceptación:** tras 2 semanas de uso, Jarvis responde "¿cómo se llamaba el proyecto de…?" y
"ponme lo de siempre" con >85 % de acierto, sin haber guardado ningún secreto.

---

## Fase 6 · Presencia y apariencia — ⬜

Aquí es donde entra el "poco a poco mejoraremos la apariencia".

- [ ] API FastAPI + WebSocket (esqueleto ya en el repo) con auth por token local
- [ ] **HUD overlay**: ventana siempre-encima, translúcida, que se activa con la wake word,
      muestra la forma de onda del audio, transcripción en vivo, acción en curso y sugerencias
- [ ] Icono de bandeja/menu bar con estados (ocioso, escuchando, pensando, necesita aprobación)
- [ ] Panel web local (Tauri): historial, auditoría, coste, monitores, configuración visual
- [ ] Sistema de temas (tokens de color, tipografía, densidad) + modo oscuro/claro automático
- [ ] Animaciones de estado (reactor JARVIS, pulsos) con coste de CPU acotado (< 3 %)
- [ ] Notificaciones nativas del SO con acciones ("Aprobar", "Ignorar 1 h")
- [ ] Atajos globales (T2/T3 approval, push-to-talk, mute)
- [ ] Accesibilidad: navegación por teclado, lector de pantalla, alto contraste

**Aceptación (G5 parcial):** abrir, aprobar una acción T2 y consultar el gasto del día sin tocar
una terminal.

---

## Fase 7 · Integraciones profundas — ⬜

- [ ] Cliente MCP: GitHub, Notion, Slack, Home Assistant, Playwright, filesystem server
- [ ] Servidor MCP de Jarvis (otras apps lo usan)
- [ ] Calendario (CalDAV/Google) y correo (IMAP/Graph) con redacción asistida
- [ ] Navegador: abrir/resumir/rellenar formularios vía Playwright
- [ ] Compañero de terminal: hook en `bash`/`zsh` que sugiere al ver un error
- [ ] Docker/K8s: estado de contenedores, logs, restarts
- [ ] Domótica y escenas (luces, música, foco)
- [ ] Spotify/MPD/playerctl, subtítulos en vivo, traducción
- [ ] Automatizaciones: "si pasa X entonces Y" con editor en el panel

---

## Fase 8 · Distribución y hardening — ⬜

- [ ] Empaquetado: PyInstaller/Nuitka por SO + instaladores (`.deb`/`.AppImage`, `.msi`, `.dmg`)
- [ ] Firma de código (Authenticode, notarización de Apple) y verificación en el updater
- [ ] Auto-update con canal estable/beta y rollback
- [ ] Hardening: sin root, sandbox de skills, permisos mínimos, cifrado de la BD local
- [ ] i18n completo es/en (catálogos `gettext`) y acentos regionales en TTS
- [ ] Documentación de usuario final + videos + solución de problemas por SO
- [ ] Telemetría **opt-in** anónima y desactivable (nunca contenido)
- [ ] Tests de instalación en máquinas limpias de los 3 SO dentro del CI

**Aceptación (G5):** instalación en < 10 min por un usuario no técnico, en los tres SO, con
actualización automática funcionando.

---

## Orden recomendado de trabajo (secuencia crítica)

```
F0 ──► F1 ──► F2 ──► F3 ──► F4 ──► F6(HUD mínimo) ──► F5 ──► F7 ──► F8
         │             │      │
         └── cache/coste └─ undo/dry-run └─ barge-in   ← los 3 puntos donde la gente abandona
```

Razón: la voz (F3) antes que la memoria (F5) porque la voz es lo que hace que se *sienta* Jarvis;
y un HUD mínimo tras F4 porque las sugerencias sin pantalla son invisibles.
