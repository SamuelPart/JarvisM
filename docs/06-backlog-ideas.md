# 06 · Backlog de ideas e integraciones

Catálogo vivo. Cada ítem indica fase sugerida, valor (V), esfuerzo (E) y riesgo (R) en escala 1–5.
Ordenado por "valor rápido primero". Cuando elijas uno, lo promovemos al roadmap con sus criterios
de aceptación.

---

## A. Control del sistema (lo que pediste primero)

| # | Idea | V | E | R | Fase | Notas |
|---|---|---|---|---|---|---|
| A1 | Abrir/cerrar apps por voz y por alias ("navegador" → firefox) | 5 | 1 | 1 | 2 | Alias aprendidos del uso |
| A2 | Gestión de ventanas: enfocar, mover, maximizar, mosaico, cambiar de workspace | 5 | 2 | 2 | 2 | `wmctrl`/`xdotool` en X11 |
| A3 | "Modo trabajo": abre IDE + terminal + navegador en el workspace correcto | 5 | 2 | 2 | 7 | Macros procedimentales |
| A4 | Control de volumen, brillo, silenciado de micro, modo no-molestar | 4 | 1 | 1 | 2 | |
| A5 | Búsqueda de archivos en lenguaje natural ("el pdf del contrato de marzo") | 5 | 3 | 2 | 5 | Necesita índice + embeddings |
| A6 | Clipboard inteligente: histórico, dedupe, "pega lo último que copié de GitHub" | 4 | 2 | 3 | 6 | Riesgo de secretos → redactor |
| A7 | Gestor de archivos por voz: mover/renombrar por lotes con reglas | 4 | 2 | 3 | 2 | Siempre con undo y dry-run |
| A8 | Captura de pantalla + "¿qué estoy viendo?" (visión) | 5 | 2 | 4 | 6 | Gemini/GPT visión; privacidad alta |
| A9 | OCR de la pantalla para buscar texto en apps sin API | 3 | 2 | 2 | 6 | `tesseract` |
| A10 | Bloqueo de pantalla, suspensión y apagado **con confirmación fuerte** | 3 | 1 | 4 | 2 | T3 siempre |
| A11 | Perfiles de energía/rendimiento ("pon modo batería") | 3 | 2 | 2 | 4 | `tlp`/`powerprofilesctl` |
| A12 | Estado de red: IP, VPN activa, ping, ancho de banda, "¿por qué va lento internet?" | 4 | 2 | 1 | 4 | |

## B. Proactividad (el "que me avise cuando algo no anda bien")

| # | Idea | V | E | R | Fase |
|---|---|---|---|---|---|
| B1 | Disco casi lleno → propone limpieza concreta con GB recuperables | 5 | 2 | 2 | 4 |
| B2 | Actualizaciones de seguridad pendientes → resumen semanal + aplicar (T3) | 5 | 2 | 3 | 4 |
| B3 | Servicios caídos (`systemctl --failed`) → diagnóstico y reinicio propuesto | 5 | 2 | 3 | 4 |
| B4 | RAM/swap saturados → top 5 procesos con explicación de qué son | 5 | 1 | 1 | 4 |
| B5 | Temperatura alta / ventilador → sugerir cerrar cargas, revisar polvo | 4 | 2 | 1 | 4 |
| B6 | Batería baja con procesos pesados → "quieres que pause X y active ahorro?" | 4 | 2 | 2 | 4 |
| B7 | SMART del disco degradado → **alerta crítica** con plan de backup | 5 | 2 | 1 | 4 |
| B8 | Puertos escuchando nuevos no reconocidos → alerta de seguridad | 5 | 2 | 2 | 4 |
| B9 | Errores nuevos en `journalctl -p err` / `dmesg` → resumen diario | 4 | 3 | 1 | 4 |
| B10 | Caches de pip/npm/Docker inflados → limpieza propuesta | 4 | 1 | 2 | 4 |
| B11 | Certificados/keys de tu dev a punto de caducar → aviso con antelación | 4 | 2 | 1 | 5 |
| B12 | "Tu comando falló 3 veces" → sugiere la corrección (hook en el shell) | 5 | 3 | 2 | 7 |
| B13 | Recordatorios y temporizadores por voz ("en 25 min avísame") | 4 | 1 | 1 | 2 |
| B14 | Briefing matutino: clima, agenda, pendientes de git, estado del equipo | 5 | 3 | 1 | 4 |
| B15 | Resumen nocturno: qué hiciste hoy, qué quedó abierto | 4 | 2 | 1 | 5 |
| B16 | Pausas de salud: postura, ojos, hidratación, sin ser pesado | 3 | 1 | 1 | 6 |

## C. Desarrollo (siendo tú usuario de Kali, esto vale oro)

| # | Idea | V | E | R | Fase |
|---|---|---|---|---|---|
| C1 | Git assistant: estado, resumen de commits del día, crear rama/PR por voz | 5 | 2 | 3 | 7 |
| C2 | Docker/K8s: estado de contenedores, logs de los últimos 5 min, restart | 4 | 2 | 3 | 7 |
| C3 | Compañero de terminal: al pegar un error, explica y propone el fix | 5 | 3 | 2 | 7 |
| C4 | Generador de comandos: "¿cómo busco los .log modificados hoy mayores de 100 MB?" | 5 | 1 | 1 | 2 |
| C5 | Explicador de scripts/binarios con análisis estático previo | 4 | 2 | 3 | 7 |
| C6 | CI watcher: avisa cuando un pipeline de GitHub Actions falla y por qué | 4 | 2 | 1 | 7 |
| C7 | Revisión de código por voz ("revisa el diff y dime riesgos") | 4 | 2 | 2 | 7 |
| C8 | Snippets/lanzador tipo Raycast o Alfred con búsqueda fuzzy + IA | 4 | 3 | 1 | 6 |

## D. Seguridad (con guardrails legales estrictos)

| # | Idea | V | E | R | Fase |
|---|---|---|---|---|---|
| D1 | Inventario de tu propia red local (solo hosts tuyos, allowlist explícita) | 4 | 3 | **5** | 7 |
| D2 | Revisión de configuración de Kali: servicios activos, sshd, firewall, sudoers | 5 | 2 | 2 | 4 |
| D3 | Gestor de secretos: genera, guarda en keyring, rota (nunca en texto plano) | 4 | 3 | 4 | 5 |
| D4 | Detector de "estás a punto de commitear una clave" (pre-commit + IA) | 5 | 1 | 1 | 2 |
| D5 | Explicador de logs de `fail2ban`/`auth.log` con intentos de acceso | 4 | 2 | 1 | 4 |
| D6 | Checklist de anonimato antes de una sesión (VPN, MAC, hostname, timezone) | 4 | 2 | 3 | 7 |
| D7 | Asistente de pentesting **ético**: solo con `scope.toml` firmado por el usuario | 4 | 4 | **5** | 7+ |

> D1 y D7 quedan fuera por defecto. Solo se activan con allowlist escrita a mano por ti, y siempre
> sobre sistemas propios o con autorización documentada. El proyecto no distribuye exploits.

## E. Vida y productividad

| # | Idea | V | E | R | Fase |
|---|---|---|---|---|---|
| E1 | Correo: leer resúmenes, redactar respuestas, "¿me escribió alguien importante?" | 4 | 3 | 4 | 7 |
| E2 | Calendario: crear/mover eventos por voz, avisos de conflicto | 5 | 2 | 2 | 7 |
| E3 | Notas por voz → Obsidian/Notion/Markdown con enlaces automáticos | 5 | 2 | 2 | 5 |
| E4 | Listas de la compra/tareas con recordatorios por contexto | 3 | 2 | 1 | 5 |
| E5 | Clima, tráfico, noticias resumidas y personalizadas | 3 | 1 | 1 | 4 |
| E6 | Música: "pon algo para concentrarme", control de Spotify/MPD | 4 | 2 | 2 | 7 |
| E7 | Domótica: luces, enchufes, escenas (Home Assistant / Matter) | 4 | 3 | 2 | 7 |
| E8 | Traducción en vivo y subtítulos de lo que suena | 3 | 3 | 2 | 6 |
| E9 | Navegador: "abre X, resume el artículo y guárdalo en notas" | 5 | 3 | 3 | 7 |
| E10 | Pomodoro/focus con bloqueo de distracciones real | 3 | 2 | 2 | 6 |

## F. Experiencia y apariencia (lo que iremos puliendo "poco a poco")

| # | Idea | V | E | R | Fase |
|---|---|---|---|---|---|
| F1 | HUD overlay estilo Iron Man: reactor, onda de voz, transcripción en vivo | 5 | 4 | 1 | 6 |
| F2 | Icono de bandeja con estados y menú rápido | 4 | 2 | 1 | 6 |
| F3 | Panel web local: historial, auditoría, gasto, monitores, config visual | 5 | 4 | 2 | 6 |
| F4 | Temas y personalización de la voz (tono, velocidad, humor) | 3 | 2 | 1 | 6 |
| F5 | Animaciones de "pensando"/"ejecutando" con coste de CPU acotado | 3 | 2 | 1 | 6 |
| F6 | Modo presentación: Jarvis callado salvo urgencias | 3 | 1 | 1 | 6 |
| F7 | Widgets de escritorio (calendario, clima, estado del equipo) | 3 | 4 | 1 | 6+ |
| F8 | Multi-dispositivo: móvil como control remoto del PC | 4 | 4 | 3 | 8 |
| F9 | Voz personalizada clonada (con consentimiento explícito) | 2 | 3 | 4 | 8 |

---

## Top 10 que yo haría primero (mi recomendación como ingeniero)

1. **A1 + A4** — abrir apps y controlar volumen/brillo. Es el "efecto wow" más barato.
2. **B1 + B4** — disco lleno y RAM saturada. Cubren el 80 % de los avisos realmente útiles.
3. **C4** — generador de comandos. Uso diario inmediato, riesgo casi nulo.
4. **B2** — actualizaciones de seguridad pendientes. En Kali esto es oro.
5. **D4** — detector de claves a punto de commitearse. Te ahorra un disgusto serio.
6. **B13** — recordatorios por voz. Demuestra que el loop de voz funciona de punta a punta.
7. **B14** — briefing matutino. La feature que hace que lo *uses* todos los días.
8. **A2** — gestión de ventanas/works. Productividad real en Linux.
9. **F2** — icono de bandeja con estados. Presencia sin coste.
10. **C1** — git assistant por voz.

Justificación: los 10 tienen valor alto (≥4), esfuerzo bajo (≤3) y riesgo controlado (≤3),
y juntos cubren las cuatro cosas que pediste: **voz, control del SO, proactividad y sugerencias**.
