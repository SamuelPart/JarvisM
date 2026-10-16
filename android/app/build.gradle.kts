// JarvisM Pro — módulo :app
//
// Las dependencias están versionadas explícitamente o agrupadas por BOM para
// mantener builds reproducibles.

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}

android {
    namespace = "com.samuelpart.jarvispro"
    // Las versiones actuales de Compose y AndroidX requieren compilar contra API 37.
    compileSdk = 37

    defaultConfig {
        applicationId = "com.samuelpart.jarvispro"
        // 26 = Android 8.0. Cubre prácticamente todo el parque móvil y es el
        // mínimo que nos deja usar iconos adaptativos y APIs modernas de audio.
        minSdk = 26
        // Compilar con API 37 no activa los cambios de ejecución de target 37.
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"
    }

    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-debug"
        }
        release {
            // Sin minificar: R8 eliminando clases @Serializable sin las reglas
            // correctas rompe kotlinx.serialization en tiempo de ejecución. Las
            // reglas ya están en proguard-rules.pro, pero por defecto no se
            // arriesga: esta app maneja una clave de API, no tamaños de APK.
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }

    lint {
        // Un lint que falle el build en la primera compilación ajena es ruido,
        // no calidad: los avisos se ven en Android Studio sin romper nada.
        abortOnError = false
    }
}

kotlin {
    compilerOptions {
        // Coherente con sourceCompatibility/targetCompatibility de arriba.
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.19.1")
    implementation("androidx.activity:activity-compose:1.13.0")

    // Compose: el BOM fija las versiones de todo el ecosistema Compose, así no
    // hay que acertar una por una (y evita el clásico desajuste ui/material3).
    implementation(platform("androidx.compose:compose-bom:2026.09.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    // Iconos: versión FIJADA a propósito. Google congeló esta librería en 1.7.8
    // (febrero de 2025) y ya no se publica en la misma "tren" que Compose, así que
    // confiar en que el BOM la gestione es arriesgarse a un
    // "Could not find androidx.compose.material:material-icons-core:" al hacer Sync.
    // Es solo el catálogo de iconos: no arrastra el resto de Compose, que sigue
    // viniendo del BOM.
    implementation("androidx.compose.material:material-icons-core:1.7.8")

    // Ciclo de vida: ViewModel + recolección de estado consciente del ciclo.
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.11.0")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.11.0")

    // Red: OkHttp da streaming incremental de verdad (leer línea a línea sin
    // cargar la respuesta entera en memoria), que es lo que necesita el SSE.
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    // JSON: tipado y testeable en la JVM sin Android (los tests unitarios usan
    // esto directamente, sin Robolectric).
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")

    // Compose en el APK de debug: previsualizaciones y herramientas.
    debugImplementation("androidx.compose.ui:ui-tooling")

    // Tests unitarios (JVM). La lógica pura — política de riesgos, parser SSE,
    // construcción de payloads, saneado de esquemas — se prueba aquí.
    testImplementation("junit:junit:4.13.2")
}
