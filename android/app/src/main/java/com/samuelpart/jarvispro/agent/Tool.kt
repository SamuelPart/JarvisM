package com.samuelpart.jarvispro.agent

import android.content.Context
import com.samuelpart.jarvispro.data.AppSettings
import com.samuelpart.jarvispro.gemini.FunctionCall
import com.samuelpart.jarvispro.gemini.ToolDeclaration
import com.samuelpart.jarvispro.gemini.ToolSchema
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Declaración de una herramienta: lo que ve el modelo. */
data class ToolSpec(
    val name: String,
    val description: String,
    val parameters: JsonObject,
    val tier: RiskTier,
)

/** Resultado de ejecutar una herramienta. */
data class ToolResult(
    val ok: Boolean,
    /** Texto corto para enseñar al usuario y devolver al modelo. */
    val summary: String,
    /** Datos estructurados de vuelta al modelo (además del resumen). */
    val data: JsonObject = JsonObject(emptyMap()),
)

/**
 * Lo que una herramienta necesita para trabajar.
 *
 * Se inyecta el contexto en vez de importar Android dentro de cada herramienta:
 * así el registro se construye una vez y las partes puras (política, esquemas,
 * payloads) se pueden probar sin teléfono.
 */
class ToolContext(
    val context: Context,
    val settings: AppSettings,
)

interface Tool {
    val spec: ToolSpec

    /**
     * ¿Está disponible con estos ajustes? Las herramientas peligrosas (SMS) se
     * quedan fuera de la lista si el usuario no las ha activado: el modelo no
     * puede llamarlas porque ni siquiera sabe que existen.
     */
    fun isEnabled(settings: AppSettings): Boolean = true

    suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult
}

class ToolRegistry(private val tools: List<Tool>) {

    fun enabledFor(settings: AppSettings): List<Tool> = tools.filter { it.isEnabled(settings) }

    fun find(name: String): Tool? = tools.firstOrNull { it.spec.name == name }

    /** Declaraciones listas para mandar a Gemini, ya saneadas. */
    fun declarations(settings: AppSettings): List<ToolDeclaration> = enabledFor(settings).map { tool ->
        ToolDeclaration(
            name = tool.spec.name,
            description = tool.spec.description,
            // El saneado va aquí, en el único punto por el que pasan todas: es
            // imposible que una herramienta "se escape" con un esquema inválido.
            parameters = ToolSchema.sanitize(tool.spec.parameters) as JsonObject,
        )
    }

    fun byCallName(name: String): Tool? =
        tools.firstOrNull { it.spec.name == name } ?: find(name.replace('_', '.'))
}

// --------------------------------------------------------------------------- //
// Ayudas para leer argumentos que llegan del modelo
// --------------------------------------------------------------------------- //

/**
 * Los argumentos que propone el modelo son texto libre y no siempre respetan los
 * tipos: llega `nivel: "70"` o `nivel: 70`, `encender: "true"` o `true`. Estas
 * funciones normalizan sin reventar, porque un `ClassCastException` aquí se
 * llevaría por delante toda la conversación.
 */
object Args {

    fun str(args: JsonObject, key: String, default: String = ""): String {
        val element = args[key] ?: return default
        return (element as? JsonPrimitive)?.content ?: default
    }

    fun intOrNull(args: JsonObject, key: String): Int? {
        val raw = str(args, key).trim()
        if (raw.isEmpty()) return null
        return raw.toIntOrNull()
            ?: raw.toDoubleOrNull()?.toInt()
            ?: raw.toFloatOrNull()?.toInt()
    }

    fun int(args: JsonObject, key: String, default: Int = 0): Int = intOrNull(args, key) ?: default

    fun boolOrNull(args: JsonObject, key: String): Boolean? {
        val raw = str(args, key).trim().lowercase()
        return when (raw) {
            "true", "1", "si", "sí", "yes", "on", "encender", "encendida" -> true
            "false", "0", "no", "off", "apagar", "apagada" -> false
            else -> null
        }
    }

    fun bool(args: JsonObject, key: String, default: Boolean = false): Boolean =
        boolOrNull(args, key) ?: default

    fun isBlank(args: JsonObject, key: String): Boolean = str(args, key).isBlank()

    /** Construye el JSON de respuesta para el modelo. */
    fun response(vararg pairs: Pair<String, JsonElement>): JsonObject = buildJsonObject {
        for ((key, value) in pairs) put(key, value)
    }

    fun text(value: String): JsonElement = JsonPrimitive(value)

    fun number(value: Int): JsonElement = JsonPrimitive(value)

    fun flag(value: Boolean): JsonElement = JsonPrimitive(value)
}

/** Extrae el nombre del modelo de una llamada, para los mensajes de registro. */
fun FunctionCall.displayName(): String = name.ifBlank { "(sin nombre)" }
