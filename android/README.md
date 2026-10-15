# JARVIS Pro (Android)

Asistente personal para el teléfono: habla con **la API de Gemini** (solo Gemini,
ningún otro proveedor) y puede **actuar sobre el teléfono** — abrir apps, poner
alarmas, cambiar el volumen, encender la linterna, leer la batería, preparar SMS —
siempre pasando por una política de riesgo que decide qué se hace solo y qué pide
permiso.

> Esta carpeta es una **app Android independiente** dentro del repositorio. El
> resto del repositorio (`jarvis/`, `tests/`…) es el proyecto de escritorio en
> Python. **Al abrir en Android Studio hay que abrir la carpeta `android/`, no la
> raíz del repositorio.**

## Empezar

👉 **[docs/COMPILAR-EN-ANDROID-STUDIO.md](docs/COMPILAR-EN-ANDROID-STUDIO.md)** —
guía paso a paso, desde clonar hasta tenerla funcionando en tu teléfono.

Otros documentos:

| Documento | Qué contiene |
|---|---|
| [docs/COMPILAR-EN-ANDROID-STUDIO.md](docs/COMPILAR-EN-ANDROID-STUDIO.md) | Instalar, clonar, abrir, ejecutar, compilar el APK y resolver errores |
| [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) | Cómo está organizado el código y por qué |
| [docs/PLAN-APP.md](docs/PLAN-APP.md) | Qué está hecho, qué falta y hacia dónde va (fases) |

## En una frase

- **Voz + texto**: dictado con el reconocedor de Android, respuestas leídas en voz
  alta (opcional).
- **Streaming**: la respuesta aparece mientras se escribe.
- **15 herramientas** del teléfono, clasificadas por riesgo (T0 leer → T3
  irreversible), con confirmación en pantalla para lo que sale de la app.
- **Clave de API por el usuario**, en los ajustes, nunca compilada en el APK.

## Requisitos

- Android Studio (versión estable reciente) con el **SDK 36** instalado.
- JDK 17 o superior (Android Studio trae el suyo).
- Un teléfono con **Android 8.0 (API 26)** o superior, o un emulador.
- Una clave de la API de Gemini, gratis en <https://aistudio.google.com> →
  *Get API key*.

Todo lo demás (Gradle incluido) lo descarga solo el proyecto: el *wrapper* viene
en el repositorio, no hace falta instalar nada a mano.
