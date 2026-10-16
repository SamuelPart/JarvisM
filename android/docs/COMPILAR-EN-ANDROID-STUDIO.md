# Cómo abrir y ejecutar JARVIS Pro en Android Studio

Guía completa, de cero a tenerla funcionando en el teléfono. Si algo falla, al
final está la tabla de errores frecuentes.

---

## 1. Antes de empezar: instala lo necesario

**En tu Kali/PC:**

1. Descarga **Android Studio** desde <https://developer.android.com/studio> y
   instálalo (en Kali es un `.tar.gz`: se descomprime y se ejecuta
   `./android-studio/bin/studio.sh`).
2. Ábrelo y deja que el asistente inicial termine. En la pantalla *Welcome*:
   - **More Actions → SDK Manager** (o *Tools → SDK Manager* ya dentro).
   - Pestaña **SDK Platforms**: marca **Android 17 (API 37)**.
   - Pestaña **SDK Tools**: marca **Android SDK Build-Tools 36**, **Android SDK
     Platform-Tools** y **Android SDK Command-line Tools**.
   - Acepta las licencias y pulsa **Apply** (descargará unos cientos de MB).

Usa Android Studio Panda 3 (2025.3.3 Patch 1) o posterior para compatibilidad
con API 37. Android Studio trae su propio JDK; no hace falta instalar Java aparte.

**En el teléfono (si vas a usar el móvil, no un emulador):**

1. Ajustes → *Acerca del teléfono* → toca 7 veces **Número de compilación** para
   activar *Opciones de desarrollador*.
2. Ajustes → *Opciones de desarrollador* → activa **Depuración por USB**.
3. Conecta el teléfono por cable. Cuando salga el aviso *¿Permitir depuración por
   USB?*, pulsa **Permitir** (marca "recordar siempre").

---

## 2. Clona el repositorio

En una terminal:

```bash
git clone https://github.com/SamuelPart/JarvisM.git
cd JarvisM
ls android
```

El proyecto de Android Studio está en la carpeta **`android/`** del clon.

> No necesitas instalar Gradle ni Kotlin: el proyecto trae el *wrapper* de Gradle
> (`android/gradlew` + `android/gradle/wrapper/`), y Android Studio descarga la
> versión exacta que necesita al abrir.

---

## 3. Ábrelo en Android Studio

1. **File → Open…**
2. Navega hasta el clon y selecciona la carpeta **`JarvisM/android`** — la carpeta
   `android`, **no** `JarvisM` ni `app`. Pulsa **OK**.
3. Si pregunta *"Trust project?"*, dile que sí.
4. Empieza el **Gradle Sync** (barra inferior). La primera vez tarda varios minutos
   porque descarga Gradle 9.3.1 y las dependencias (Compose, OkHttp…). Necesita
   internet.
5. Cuando termine, abajo debe poner **"Gradle sync finished"** o simplemente
   desaparecer la barra. Si sale un error rojo, ve a la sección 8.

Comprobación rápida: a la izquierda, en la vista **Project → Android**, debes ver
`app/java/com.samuelpart.jarvispro` con los paquetes `agent`, `data`, `gemini`,
`ui` y `voice`.

### Alternativa sin terminal

En la pantalla de bienvenida de Android Studio: **Get from VCS** → pega
`https://github.com/SamuelPart/JarvisM` → *Clone*. Después, abre la carpeta
`android` del clon con *File → Open*.

---

## 4. Ejecútala en tu teléfono

1. En la barra superior, a la derecha del botón ▶️, comprueba que aparece tu
   teléfono en la lista de dispositivos. Si no aparece, pulsa el icono de
   refrescar; si sigue sin salir, revisa la depuración USB (paso 1).
2. Pulsa **▶️ Run 'app'** (Shift+F10).
3. La primera compilación tarda un par de minutos. Luego la app se instala y se
   abre sola en el teléfono.
4. En el teléfono puede salir *"¿Instalar esta aplicación?"* → **Instalar**.

La app se llama **JARVIS Pro**. Verás "JARVIS" grande y varios botones de ejemplo.

### Si prefieres un emulador

1. **Tools → Device Manager → Create device**.
2. Elige un **Pixel 7** (o similar) → *Next* → sistema **API 36** (o API 37 si
   quieres probar la versión más reciente) → *Next* → **Finish**.
3. Lanza el emulador con el ▶️ de al lado y luego ejecuta la app igual que antes.

---

## 5. Primer uso: pon tu clave de Gemini

1. En el teléfono, dentro de la app, pulsa el **engranaje ⚙️** (arriba a la
   derecha).
2. En **Clave de la API de Gemini**, pega tu clave (`AQ.Ab8…` o `AIza…`).
   - Se consigue gratis en <https://aistudio.google.com> → *Get API key*.
   - Se guarda **solo en este teléfono**, en el almacén privado de la app, y no
     entra en copias de seguridad. (Detalle técnico y su límite están explicados
     en `ARQUITECTURA.md`.)
3. Pulsa **Probar conexión**: debe responder algo como *"Conexión correcta con
   «gemini-3.8-flash». Respondió: «…»"*.
   - Si te da error, mira la tabla del final. Para saber qué modelos acepta tu
     clave, pulsa **Ver modelos**.
4. Pulsa **Guardar**. Vuelve al chat.

---

## 6. Pruébala

Escríbele o pulsa **Hablar** (la primera vez pedirá permiso de micrófono). Cosas
que puedes decirle:

| Dile esto | Qué debería pasar |
|---|---|
| "¿Cuánta batería me queda?" | Consulta la batería (no toca nada) |
| "Pon una alarma a las 6:30" | Abre el reloj con la alarma preparada |
| "Abre WhatsApp" | Abre WhatsApp (pide confirmación) |
| "Sube el volumen al 70 %" | Cambia el volumen de multimedia |
| "Enciende la linterna" | Enciende el flash de la cámara |
| "¿Qué apps tengo instaladas?" | Lista las apps con lanzador |
| "Prepara un SMS a Ana que diga 'llego en 10'" | Abre Mensajes con el texto puesto |

Cuando Jarvis quiera hacer algo que sale de la app, aparece un diálogo
**"¿Le dejo hacerlo?"** con los argumentos exactos y el nivel de riesgo. Si dices
*Cancelar*, el modelo se entera y sigue la conversación sin hacerlo.

Si quieres que **pregunte antes de todo**, actívalo en Ajustes → *Pedirme permiso
antes de CADA acción*.

---

## 7. Compilar el APK (sin cable, para instalarlo a mano)

**Desde Android Studio:** *Build → Build Bundle(s) / APK(s) → Build APK(s)*.
Cuando termine, pulsa *locate* y tendrás:

```
android/app/build/outputs/apk/debug/app-debug.apk
```

Copia ese archivo al teléfono y ábrelo (habrá que permitir "instalar apps de
origen desconocido" para el explorador de archivos que uses).

**Desde la terminal** (con el SDK instalado):

```bash
cd JarvisM/android
./gradlew assembleDebug          # genera el APK de depuración
./gradlew installDebug           # lo instala en el teléfono conectado
./gradlew test                   # ejecuta los tests unitarios
./gradlew lint                   # análisis estático
```

Si `./gradlew` se queja de que no encuentra el SDK, crea el fichero
`android/local.properties` con tu ruta:

```properties
sdk.dir=/home/TU_USUARIO/Android/Sdk
```

(Ese fichero está en `.gitignore`: es tuyo, no se sube.)

---

## 8. Errores frecuentes y qué hacer

| Error | Causa y solución |
|---|---|
| `SDK location not found` | Abre el proyecto desde Android Studio (lo rellena solo) o crea `local.properties` como en el paso 7 |
| `Unsupported class file major version` / `invalid source release` | El JDK de Gradle es viejo: *Settings → Build, Execution, Deployment → Build Tools → Gradle → Gradle JDK* → elige **jbr-21** (el que trae Android Studio) |
| `Could not resolve androidx.compose...` / `Failed to download...` | Sin internet, o hay un proxy/VPN bloqueando `dl.google.com` y `repo.maven.apache.org`. Comprueba la conexión y reintenta *File → Sync Project with Gradle Files* |
| `requires compileSdk 37` / `requires Android Gradle plugin 9.1.0 or higher` | El proyecto necesita AGP 9.1.1, Gradle 9.3.1 y SDK Platform 37. Confirma que Android Studio sincronizó la versión nueva; `targetSdk` puede seguir en 36. |
| `compileSdk 37 not found` / `platform 37 missing` | Falta el SDK 37: *Tools → SDK Manager → SDK Platforms* → marca **Android 17 (API 37)** → Apply |
| `Gradle sync failed: timeout` | Primera descarga lenta: reintenta. Si se repite, sube el límite en `android/gradle.properties` (`org.gradle.jvmargs`) o usa una red mejor |
| Al ejecutar: `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | Hay otra versión instalada con otra firma: desinstala "JARVIS Pro" del teléfono y vuelve a ejecutar |
| La app abre pero dice *"Falta la clave"* | No has guardado la clave: ⚙️ → pega la clave → **Guardar** |
| `Clave de API rechazada (401/403)` | Clave mal copiada (¿espacios?), caducada o de otro proyecto. Genera una nueva en AI Studio |
| `El modelo «X» no está disponible (404)` | Ese modelo no existe para tu clave: ⚙️ → **Ver modelos** y elige uno de la lista |
| `Límite de peticiones (429)` | Cuota gratuita agotada: espera un minuto o cambia a un modelo `flash-lite` |
| No aparece el teléfono en Android Studio | Depuración USB activada, cable de datos (no solo carga), pulsa *Permitir* en el teléfono, y `adb devices` en la terminal para verificar |
| El micrófono no funciona | Concede el permiso: Ajustes del teléfono → Apps → JARVIS Pro → Permisos → Micrófono |

---

## 9. Qué NO hace todavía

- **No hay conversación por voz bidireccional** (tipo llamada): es la Fase 2, con
  la Live API de Gemini. Hoy la voz es dictado + lectura de respuestas.
- **No hay palabra de activación** ("Oye Jarvis"): no hay servicio en segundo plano.
- **No hay widget ni HUD** en la pantalla de inicio.
- **No envía SMS** salvo que lo actives explícitamente en Ajustes (y aun así,
  siempre pide confirmación antes de enviar).

El plan completo, con lo que ya está hecho, está en `PLAN-APP.md`.
