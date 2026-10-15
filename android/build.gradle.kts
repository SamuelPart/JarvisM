// JarvisM Pro (Android) — build de raíz.
//
// Aquí solo se DECLARAN los plugins (con `apply false`): cada módulo decide
// cuáles aplica. Se centraliza la versión para que Kotlin, el compilador de
// Compose y el de serialización viajen SIEMPRE en la misma versión, que es un
// requisito real: los tres se publican juntos desde el repositorio de Kotlin, y
// mezclarlos da errores de compilación difíciles de leer.
//
// Versiones (verificadas contra los repositorios oficiales, oct-2026):
//   - AGP 8.13.0  → probado hasta compileSdk 36.1 (por eso compileSdk = 36)
//   - Gradle 8.14.6 (en gradle/wrapper/gradle-wrapper.properties)
//   - Kotlin 2.4.10
//   - Compose BOM 2026.09.00
plugins {
    id("com.android.application") version "8.13.0" apply false
    id("org.jetbrains.kotlin.android") version "2.4.10" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.10" apply false
    id("org.jetbrains.kotlin.plugin.serialization") version "2.4.10" apply false
}
