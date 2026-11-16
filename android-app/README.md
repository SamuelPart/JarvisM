# JARVIS para Android — primera versión

Esta aplicación es independiente: la laptop no necesita estar encendida. No se conecta a Termux ni comparte automáticamente cuentas, historial, recordatorios, permisos o configuración con la versión de escritorio. Tampoco lee el `.env` de escritorio ni inyecta sus claves en el APK. Requiere Android 8 o posterior, un servicio de reconocimiento de voz instalado y, para conversar con la IA, Internet y una clave configurada dentro de Ajustes de la propia aplicación.

## Lo que incluye

- Interfaz con orbe programático, chat escrito y botón **Hablar**.
- Respuestas en voz con el motor de texto a voz de Android; su voz depende de la configuración del teléfono, no es necesariamente Edge Jorge.
- Consulta local de hora y batería y solicitud para abrir Ajustes, Chrome, YouTube o WhatsApp cuando la aplicación está en primer plano. Abrir una app no verifica su estado ni envía mensajes.
- Escucha de «Jarvis» como sesión opcional en primer plano con notificación permanente y botón Detener. Se activa únicamente desde la app visible y con consentimiento de micrófono. Di «Jarvis» seguido de tu pregunta; si dices solo «Jarvis», espera a que pregunte y habla. La sesión no se inicia sola al reiniciar el teléfono.
- **Proveedor de IA: NVIDIA (predeterminado) o Gemini.** En Ajustes eliges el proveedor y guardas su clave por separado (ambas cifradas con Android Keystore). NVIDIA usa el mismo modelo de escritorio `nvidia/nemotron-3.5-bolt-e4b` contra `integrate.api.nvidia.com`. La clave nunca se imprime, no viaja en la URL ni se incluye en copias de seguridad ni en el APK. Si Keystore no está disponible, no se guarda.
- **Conseguir la clave NVIDIA:** entra a `build.nvidia.com`, inicia sesión con tu cuenta NVIDIA, genera una «API key» y pégala en Ajustes de la app. El valor de `NVIDIA_API_KEY` de tu `.env` de escritorio es el mismo que necesitas aquí; puedes abrir ese archivo en la Kali y copiarla sin pegarla en el chat ni publicarla.
- La app no puede recibir la clave desde la laptop automáticamente: hay que escribirla o pegarla una vez en Ajustes del teléfono.

El reconocimiento de voz usa el servicio de Android y **puede enviar el audio a su proveedor**, especialmente durante la escucha en segundo plano. La pregunta se envía al proveedor de IA que elijas. Lee el aviso y acepta explícitamente antes de activar escucha. En Android 13+ se solicita permiso de notificaciones. Android o el fabricante pueden interrumpir la escucha por restricciones de batería, pantalla bloqueada, red, permisos o servicio de reconocimiento; no es una palabra de activación local ni se garantiza escucha continua. Si el teléfono no permite la escucha, usa el botón Hablar. Al usar Hablar o enviar un mensaje escrito se detiene la escucha de fondo para evitar competencia de micrófono y eco. El servicio deja de escuchar mientras responde.

**Limitaciones importantes:** esta primera versión no incluye Gmail, calendario, recordatorios, correo programado, archivos, clima, automatización general, llamadas, mensajes, control de otras aplicaciones ni memoria compartida con escritorio. No se deben afirmar acciones no implementadas. No lee credenciales del proyecto ni instala programas de manera autónoma. No escucha por defecto al instalar ni arranca al encender el teléfono.

## Compilar

Requiere JDK 17, Android SDK con plataforma 35 y herramientas de compilación, Gradle y acceso a Google Maven y repositorios Gradle. En `android-app`, ejecuta `./gradlew assembleDebug`. El APK de depuración queda en `app/build/outputs/apk/debug/app-debug.apk`. El flujo GitHub Actions `Android app` compila y sube ese APK como artefacto temporal cuando está habilitado.

Para compilación continua en GitHub Actions, la persona administradora puede añadir manualmente el archivo `.github/workflows/android-app.yml` (esta integración no tiene permiso para crear archivos de flujo de trabajo, por eso no se incluye en el repositorio):

```yaml
name: Android app
on:
  push:
    paths: ['android-app/**', '.github/workflows/android-app.yml']
  workflow_dispatch:
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '17'
      - uses: gradle/actions/setup-gradle@v4
      - run: ./gradlew --no-daemon assembleDebug
        working-directory: android-app
      - uses: actions/upload-artifact@v4
        with:
          name: jarvis-android-debug
          path: android-app/app/build/outputs/apk/debug/app-debug.apk
          if-no-files-found: error
          retention-days: 14
```

También puedes abrir la carpeta `android-app/` con Android Studio, esperar la sincronización de Gradle (requiere Internet para Google Maven y la distribución de Gradle) y usar **Run**, o ejecutar `./gradlew assembleDebug` en una máquina con JDK 17 y Android SDK 35.

El APK de depuración es para pruebas; no es una publicación de Play Store. Cada entorno de compilación puede usar una clave de firma distinta, por lo que instalar una versión posterior puede exigir desinstalar la anterior y perder sus datos locales. No distribuya una clave de firma privada ni ninguna clave API. Prueba permisos, voz, pantalla bloqueada, seguridad y consumo de batería en un dispositivo real antes de confiar en ella.
