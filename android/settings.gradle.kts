// JarvisM Pro (Android) — configuración del proyecto Gradle.
//
// Nota para quien llegue aquí desde Android Studio: este proyecto es un módulo
// Android independiente. Si vas a abrirlo, abre ESTA carpeta (android/), no la
// raíz del repositorio JarvisM (que es el proyecto Python).

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
