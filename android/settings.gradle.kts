// JarvisM Pro (Android) — configuración del proyecto Gradle.
//
// Este repositorio contiene únicamente la aplicación Android. Abre esta carpeta
// (`android/`) en Android Studio para cargar el proyecto Gradle.

pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "JarvisPro"
include(":app")
