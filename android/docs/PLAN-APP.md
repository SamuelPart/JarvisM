# Plan de JARVIS Pro (Android)

Qué está hecho, qué falta y en qué orden. Estado a **15 de octubre de 2026**.

---

## Fase 1 — Base sólida ✅ (hecha)

| Pieza | Estado |
|---|---|
| Cliente de Gemini (generación, streaming SSE, listado de modelos, errores traducidos) | ✅ |
| Limpieza de esquemas de herramientas (el bug de `additionalProperties`) | ✅ |
| Bucle de agente con *function calling*, reintentos de contexto y firmas de Gemini 3 | ✅ |
| 15 herramientas del teléfono en 4 familias, con niveles de riesgo T0–T3 | ✅ |
| Política de riesgo + confirmación en pantalla para lo que sale de la app | ✅ |
| Chat con streaming, historial persistente y autoscroll | ✅ |
| Ajustes: clave, modelo, personalidad, creatividad, voz, permisos peligrosos | ✅ |
| Dictado por voz + lectura de respuestas en voz alta | ✅ |
| Tests unitarios de la lógica pura (esquemas, stream, política, argumentos, historial) | ✅ |
| Documentación (esta carpeta) | ✅ |
| **Compilar y probar en un teléfono de verdad** | ⏳ pendiente (lo hace el usuario) |

Las cuatro cosas que pediste (voz, apps/ventanas, memoria, HUD) están cubiertas así
en esta fase: **voz** = dictado + lectura; **apps/ventanas** = abrir apps y ajustes;
**memoria** = historial en el teléfono; **HUD** = pendiente (Fase 3).

---

## Fase 2 — Conversación natural por voz

Objetivo: hablarle sin tocar la pantalla y que conteste hablando, como en una
llamada.

1. **Gemini Live API** (`BidiGenerateContent` por WebSocket): audio de ida y vuelta,
   con interrupción ("barge-in": hablas y Jarvis se calla a media frase).
2. **Palabra de activación** ("Oye Jarvis") con un servicio en primer plano y
   notificación permanente.
3. **Manos libres continuo** con cancelación de eco para no oírse a sí mismo.

Lo que hay que resolver antes: permisos de micrófono en segundo plano (Android 14+
es estricto), batería y que la notificación sea honesta sobre lo que hace.

---

## Fase 3 — Un asistente que vive en el teléfono

1. **HUD / widget** en la pantalla de inicio: burbuja flotante o atajo rápido que
   abre el dictado sin entrar a la app.
2. **Memoria de verdad**: ahora el historial es una lista de mensajes. La idea es
   extraer y guardar hechos ("trabaja de noche", "su hermana se llama Ana") en una
   tabla aparte y consultarlos cuando hagan falta, con un botón para verlos y
   borrarlos.
3. **Automatizaciones**: "cuando llegue a casa, pon el volumen al 30 %" (traslada
   ideas del proyecto de escritorio).
4. **Más herramientas**: calendario (leer eventos, no solo crear), correo, música
   (control de reproducción), portapapeles, compartir pantalla… cada una con su
   nivel de riesgo y su confirmación.
5. **Varios proveedores, opcional**: hoy es solo Gemini por decisión explícita. Si
   algún día se quiere *failover*, el punto de extensión es `GeminiClient` +
   `JarvisAgent` (la política y las herramientas no cambiarían).

---

## Ideas aparcadas (buenas, pero no ahora)

- **Modo coche**: interfaz con botones enormes y voz continua.
- **Respuestas con imagen**: Gemini puede generar imágenes; habría que decidir si
  tiene sentido en un asistente de voz.
- **Exportar/importar ajustes** cifrados para pasar de un teléfono a otro.
- **Cifrado de la clave con Keystore** (ver `ARQUITECTURA.md`): necesario antes de
  publicar en cualquier tienda.

---

## Cómo se decide qué se hace solo

Cualquier función nueva tiene que responder a esto antes de escribirse:

1. **¿Se puede deshacer?** Si no → T3, confirmación siempre.
2. **¿Sale de la app o del teléfono?** Sí → T2, y el usuario ve qué va a pasar.
3. **¿El usuario tiene que dar un permiso peligroso?** → la función debe tener una
   alternativa sin permisos (como `compose_sms` frente a `send_sms`).
4. **¿El modelo podría abusar de esto con texto de terceros?** (un SMS, una web) →
   validar y limitar (lista blanca de URLs, sin esquemas raros).
