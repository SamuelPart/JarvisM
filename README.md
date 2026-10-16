# JARVIS Pro para Android

Este repositorio está dedicado exclusivamente a la app nativa **JARVIS Pro para Android**. Incluye el código Kotlin/Jetpack Compose, los tests, el wrapper de Gradle y la documentación de la aplicación.

## Abrir y ejecutar

1. Instala Android Studio Panda 3 (2025.3.3 Patch 1) o posterior y el SDK 37; incluye un JDK compatible.
2. Abre la carpeta **`android/`** en Android Studio (no la raíz del repositorio).
3. Espera a que termine Gradle Sync y pulsa **Run** con un teléfono o emulador conectado.
4. Añade tu clave de Gemini en **Ajustes** dentro de la app. La clave no se guarda en este repositorio ni se incluye en el APK.

También puedes compilar desde una terminal con JDK y Android SDK configurados:

```bash
cd android
./gradlew testDebugUnitTest
./gradlew assembleDebug
```

La guía paso a paso está en [android/docs/COMPILAR-EN-ANDROID-STUDIO.md](android/docs/COMPILAR-EN-ANDROID-STUDIO.md). Para conocer las funciones, la arquitectura y el plan, consulta [android/README.md](android/README.md) y la carpeta [android/docs/](android/docs/).
