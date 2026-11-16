# JARVIS para Android — primera versión

Esta aplicación es independiente: la laptop no necesita estar encendida. No se conecta a Termux ni comparte automáticamente cuentas, historial, recordatorios, permisos o configuración con la versión de escritorio. Requiere Android 8 o posterior, un servicio de reconocimiento de voz instalado y, para conversar con la IA, Internet y una clave Gemini configurada dentro de Ajustes de la propia aplicación.

## Lo que incluye

- Interfaz con orbe programático, chat escrito y botón **Hablar**.
- Respuestas en voz con el motor de texto a voz de Android; su voz depende de la configuración del teléfono, no es necesariamente Edge Jorge.
- Consulta local de hora y batería y solicitud para abrir Ajustes, Chrome, YouTube o WhatsApp cuando la aplicación está en primer plano. Abrir una app no verifica su estado ni envía mensajes.
- Escucha de «Jarvis» como sesión opcional en primer plano con notificación permanente y botón Detener. Se activa únicamente desde la app visible y con consentimiento de micrófono. Di «Jarvis» seguido de tu pregunta; si dices solo «Jarvis», espera a que pregunte y habla. La sesión no se inicia sola al reiniciar el teléfono.
- La clave Gemini se cifra mediante Android Keystore, no se imprime ni se coloca en la URL; no se incluye en copias de seguridad. Se introduce en Ajustes de la app, nunca en el chat. Si Keystore no está disponible, no se guarda.

El reconocimiento de voz usa el servicio de Android y **puede enviar el audio a su proveedor**, especialmente durante la escucha en segundo plano. La pregunta se envía a Gemini. Lee el aviso y acepta explícitamente antes de activar escucha. En Android 13+ se solicita permiso de notificaciones. Android o el fabricante pueden interrumpir la escucha por restricciones de batería, pantalla bloqueada, red, permisos o servicio de reconocimiento; no es una palabra de activación local ni se garantiza escucha continua. Si el teléfono no permite la escucha, usa el botón Hablar. Al usar Hablar o enviar un mensaje escrito se detiene la escucha de fondo para evitar competencia de micrófono y eco. El servicio deja de escuchar mientras responde.

**Limitaciones importantes:** esta primera versión no incluye Gmail, calendario, recordatorios, correo programado, archivos, clima, automatización general, llamadas, mensajes, control de otras aplicaciones ni memoria compartida con escritorio. No se deben afirmar acciones no implementadas. No lee credenciales del proyecto ni instala programas de manera autónoma. No escucha por defecto al instalar ni arranca al encender el teléfono.

## Compilar

Requiere JDK 17, Android SDK con plataforma 35 y herramientas de compilación, Gradle y acceso a Google Maven y repositorios Gradle. En `android-app`, ejecuta `./gradlew assembleDebug`. El APK de depuración queda en `app/build/outputs/apk/debug/app-debug.apk`. El flujo GitHub Actions `Android app` compila y sube ese APK como artefacto temporal cuando está habilitado.

Para compilación continua en GitHub Actions, el repositorio puede añadir `.github/workflows/android-app.yml` que ejecute `./gradlew --no-daemon assembleDebug` con Java 17 y Android SDK 35 y suba `app/build/outputs/apk/debug/app-debug.apk` como artefacto. Esta integración no tiene permiso para crear archivos de flujo de trabajo, por eso no se incluye; la persona administradora puede añadirlo manualmente si lo desea.

El APK de depuración es para pruebas; no es una publicación de Play Store. Cada entorno de compilación puede usar una clave de firma distinta, por lo que instalar una versión posterior puede exigir desinstalar la anterior y perder sus datos locales. No distribuya una clave de firma privada ni la clave Gemini. Prueba permisos, voz, pantalla bloqueada, seguridad y consumo de batería en un dispositivo real antes de confiar en ella.
