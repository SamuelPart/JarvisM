# Reglas de ProGuard/R8 para JarvisM Pro.
#
# Ahora mismo el release NO minifica (isMinifyEnabled = false en app/build.gradle.kts),
# así que este fichero está preparado por si lo activas más adelante: sin estas
# reglas, R8 elimina las clases @Serializable y kotlinx.serialization falla en
# tiempo de ejecución con "Serializer for class 'X' is not found".

# kotlinx.serialization: conservar serializadores generados.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class **$$serializer { *; }
-keepclasseswithmembers class * {
    kotlinx.serialization.KSerializer serializer(...);
}
-keep,includedescriptorclasses class com.samuelpart.jarvispro.**$$serializer { *; }
-keepclassmembers class com.samuelpart.jarvispro.** {
    *** Companion;
}
-keepclasseswithmembers class com.samuelpart.jarvispro.** {
    kotlinx.serialization.KSerializer serializer(...);
}

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
