# Arquitectura de JARVIS Pro

Cómo está organizado el código y por qué está hecho así. Si vas a tocar algo,
empieza por aquí.

---

## Vista general

```
app/src/main/java/com/samuelpart/jarvispro/
├── MainActivity.kt          entrada de la app: chat ⇄ ajustes
├── Json.kt                  configuración de JSON compartida por todas las capas
├── gemini/                  todo lo que habla con la API de Gemini
│   ├── GeminiClient.kt      HTTP: generate, stream (SSE), listModels, errores
│   ├── GeminiDtos.kt        modelos de datos de la API (a mano)
│   ├── SseParser.kt         parseo del stream de eventos
│   └── ToolSchema.kt        limpieza de esquemas ⚠️ (ver más abajo)
├── agent/                   el "cerebro": decide y actúa
│   ├── JarvisAgent.kt       bucle de conversación con herramientas
│   ├── AgentEvent.kt        lo que va pasando durante un turno
│   ├── Tool.kt              interfaz de herramienta, registro y lectura de args
│   ├── Policy.kt            niveles de riesgo y decisiones (puro, testeable)
│   ├── JarvisTools.kt       catálogo de las 14 herramientas
│   └── tools/               las herramientas, por familia
├── data/                    ajustes e historial
├── voice/                   dictado (SpeechRecognizer) y lectura (TTS)
└── ui/                      Compose: chat, ajustes, tema y ViewModel
```

La regla de oro: **las capas de abajo no saben que existen las de arriba.**

- `gemini/` no conoce Android ni el agente: es HTTP + JSON.
- `agent/` no conoce Compose: emite eventos (`AgentEvent`) y quien los reciba
  decide qué pintar.
- `ui/` no llama a la API: pide cosas al ViewModel.
- `Policy.kt` no conoce nada: es una función pura, y por eso se puede probar.

---

## El bucle del agente, paso a paso

```
usuario: "pon una alarma a las 6:30"
   │
   ├─ JarvisAgent envía: conversación + systemPrompt + 14 declaraciones de herramientas
   │
   ├─ Gemini responde (en streaming):
   │     texto: "Voy a programarla."
   │     functionCall: set_alarm(hora="06:30")   ← junto a su thoughtSignature
   │
   ├─ Policy.decide(T2, confirmarTodo=false) → ALLOW
   │
   ├─ Se ejecuta: abre el reloj con la alarma puesta
   │
   ├─ Se devuelve al modelo: functionResponse{resultado:"ok", resumen:"..."}
   │
   └─ Gemini cierra: "Lista para las 6:30. Pasa por el reloj para confirmarla."
```

Detalles que importan:

1. **Los `parts` del modelo se reenvían sin tocar.** Gemini 3 firma cada llamada a
   función con un `thoughtSignature`; si se reconstruyen los parts a mano y la
   firma se pierde, la siguiente petición falla con **400 "thought signature is
   missing"**. Por eso el agente guarda `List<Part>` y no texto plano.
2. **Las herramientas se ejecutan una sola vez cada una**: si el modelo repite la
   misma llamada en varios eventos del stream, se deduplica por nombre+argumentos.
3. **El contexto se recorta por delante, pero solo cortando turnos completos.** Si
   el primer elemento fuese el resultado de una herramienta, quedaría huérfano (una
   `functionResponse` sin su `functionCall` es inválida) y la API daría 400.
4. **Tope de 6 rondas** por mensaje del usuario: evita bucles infinitos de
   "herramienta → modelo → herramienta".

---

## Los niveles de riesgo (lo más importante del proyecto)

| Nivel | Significado | Ejemplos | ¿Pide permiso? |
|---|---|---|---|
| **T0** | Solo leer | batería, hora, apps instaladas | Nunca |
| **T1** | Reversible y local | volumen, linterna, brillo | Solo con "confirmar todo" |
| **T2** | Sale de la app | abrir app, ajustes, web, llamar, alarma, SMS preparado | Solo con "confirmar todo" |
| **T3** | **Irreversible** | enviar SMS de verdad | **Siempre** |

Dos decisiones deliberadas:

- **T3 nunca se salta la confirmación**, ni aunque el usuario active "confiar en
  todo". Enviar un mensaje no se puede deshacer; el resto sí (el volumen se vuelve
  a subir, la linterna se apaga, la app se cierra).
- **La herramienta de SMS no existe si el usuario no la activa.** No es solo que se
  bloquee al ejecutarla: `isEnabled()` la saca del catálogo, así que el modelo ni
  siquiera sabe que puede enviar mensajes. Menos superficie, menos sorpresas.

`open_web` además pasa por una lista blanca de esquemas (`http`/`https`) para que
el modelo —o el texto de un mensaje ajeno— no pueda colar un `javascript:` o un
`file://`.

---

## Compatibilidad de los esquemas de herramientas con Gemini

La API de Gemini acepta solo un subconjunto de JSON Schema para los parámetros de
las herramientas. Rechaza la palabra clave `additionalProperties`:

```
HTTP 400: Invalid JSON payload received. Unknown name "additionalProperties"
at 'tools[0].function_declarations[0].parameters': Cannot find field.
```

Resultado: el 100 % de los turnos fallaban.

Aquí el saneado vive en **un único punto**: `ToolRegistry.declarations()` pasa cada
esquema por `ToolSchema.sanitize()` justo antes de enviarlo. Es imposible que una
herramienta nueva "se escape" con un esquema inválido, porque no hay otra vía.

`ToolSchema` además:

- convierte `const` → `enum` de un valor,
- traduce `type: ["string","null"]` → `type:"string" + nullable:true`,
- quita `$schema`, `definitions`, `examples`, `if/then/else`…,
- **no muta el esquema original** (el original sigue sirviendo para validar),
- es idempotente (aplicarlo dos veces da lo mismo).

Todo esto está cubierto por `app/src/test/java/.../ToolSchemaTest.kt`.

---

## La clave de API

- Se pide en **Ajustes** y se guarda en el `SharedPreferences` privado de la app.
- `android:allowBackup="false"` + `data_extraction_rules.xml` vacío: **no** entra en
  copias de seguridad ni se transfiere a otro teléfono.
- En pantalla se muestra enmascarada: `AQ.Ab8RN6IY8…9f2c (39 caracteres)`.
- **Nunca** va compilada en el APK ni en `BuildConfig`: eso la expondría a
  cualquiera que descompile la app.
- **Límite honesto**: `SharedPreferences` no está cifrado. En un teléfono con root
  se puede leer. Para uso personal es un riesgo asumible y el compromiso elegido
  para no arrastrar dependencias abandonadas (`androidx.security-crypto` está
  descontinuado). Si algún día la app se publica, hay que cifrarla con una clave
  del **Keystore** de Android.
- **Nunca** se envía a ningún sitio que no sea `generativelanguage.googleapis.com`.

---

## Decisiones técnicas y por qué

| Decisión | Motivo |
|---|---|
| **DTOs escritos a mano** en vez del SDK de Gemini | El SDK de Android para Gemini quedó deprecado a favor de Firebase AI Logic (obliga a meter Firebase). A mano, además, controlamos el payload byte a byte — que es lo que permite limpiar los esquemas |
| **OkHttp** en vez de Retrofit | Necesitamos leer el stream SSE línea a línea; para 3 endpoints, Retrofit solo añadiría ceremonia |
| **Streaming con `streamGenerateContent?alt=sse`** | La respuesta aparece mientras se escribe. El `readTimeout` está en 180 s porque una respuesta con razonamiento puede tardar |
| **Sin sala de datos**: SharedPreferences + un JSON | Son 11 ajustes y un historial. Room arrastraría un procesador de anotaciones y otra versión que acertar |
| **Sin Navigation Compose** | Son dos pantallas y un booleano. Una librería de navegación aquí es más código y más piezas que puedan romperse |
| **`encodeDefaults = false`** | Los campos nulos no se envían. Mandar `"role": null` a la API da 400 |
| **Herramientas que abren la interfaz del sistema** (`ACTION_DIAL`, `ACTION_SET_ALARM`, `ACTION_INSERT`) en vez de hacer la acción directamente | No hacen falta permisos peligrosos, el usuario ve lo que va a pasar y mantiene el control. Enviar un SMS de verdad sí requiere permiso, y por eso es T3 |
| **El reconocedor de Android para el dictado** | Gratis, sin claves extra y funciona sin conexión en muchos móviles. La voz bidireccional con Live API es la Fase 2 |
| **Locales fijos con textos en español** | Es una app de una persona para su uso diario. Internacionalizarla sería trabajo sin beneficio ahora mismo |

---

## Tests

Los tests viven en `app/src/test/` y **no necesitan teléfono ni emulador**
(`./gradlew test`), porque todo lo que prueban es lógica pura. Son **45 tests en 5
ficheros**:

| Fichero | Qué protege |
|---|---|
| `ToolSchemaTest` | El bug de `additionalProperties` y el resto de traducciones de esquemas |
| `SseParserTest` | El parseo del stream: eventos partidos, keep-alives, errores dentro del stream, firmas |
| `PolicyTest` | Que T3 siempre confirme y que la lista blanca de URLs siga siéndolo |
| `ArgsTest` | Que un `"70"` en vez de `70`, o un `"sí"` en vez de `true`, no rompan nada |
| `HistorySerializationTest` | Que el formato del historial en disco siga cargando (incluso con ficheros de versiones futuras) |

Lo que **no** está cubierto: la interfaz de Compose y las herramientas que tocan
Android de verdad (requieren un test instrumentado y un dispositivo).

---

## Cómo añadir una herramienta nueva

1. Crea la clase en `agent/tools/`, implementando `Tool`:
   - `spec`: nombre, descripción **para el modelo**, esquema de parámetros y nivel.
   - `execute`: hace el trabajo y devuelve un `ToolResult` (resumen + datos).
2. Añádela a `JarvisTools.registry()`.
3. Elige bien el `tier`: si tiene efectos que no se pueden deshacer, es T3.
4. Añade un test si la lógica se puede aislar (validaciones, formateos, política).

No hay que tocar el agente, ni la interfaz, ni la política.
