// JARVIS Pro — configuración raíz de Gradle para Android.
//
// AGP 9.1.1 admite API 37 y requiere Gradle 9.3.1.
// AGP ya incluye soporte para Kotlin; el plugin kotlin-android no se aplica.
// Fijamos KGP en 2.4.10 para mantener alineados Kotlin, Compose y Serialization.
buildscript {
    repositories {
        google()
        mavenCentral()
    }
    dependencies {
        classpath("org.jetbrains.kotlin:kotlin-gradle-plugin:2.4.10")
    }
}

plugins {
    id("com.android.application") version "9.1.1" apply false
    id("org.jetbrains.kotlin.plugin.compose") version "2.4.10" apply false
    id("org.jetbrains.kotlin.plugin.serialization") version "2.4.10" apply false
}
