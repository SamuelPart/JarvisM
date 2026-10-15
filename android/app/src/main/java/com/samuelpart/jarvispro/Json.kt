package com.samuelpart.jarvispro

import kotlinx.serialization.json.Json

/**
 * Configuración única de JSON para toda la app.
 *
 * - `ignoreUnknownKeys`: la API de Gemini añade campos con frecuencia (por
 *   ejemplo `thoughtSignature`); ignorarlos evita que un cambio suyo rompa la app.
 * - `encodeDefaults = false`: es lo que hace que los campos nulos o por defecto
 *   NO se envíen. Importante: mandar `"role": null` a la API da un 400.
 *
 * (`explicitNulls` no se toca a propósito: sigue marcado como experimental y no
 * hace falta, porque todos los campos opcionales tienen `= null` por defecto.)
 */
val JarvisJson: Json = Json {
    ignoreUnknownKeys = true
    encodeDefaults = false
}
