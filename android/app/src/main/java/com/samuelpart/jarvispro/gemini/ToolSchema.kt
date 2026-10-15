package com.samuelpart.jarvispro.gemini

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Adapta JSON Schemas al subconjunto que acepta la API de Gemini.
 *
 * **Este fichero existe por un bug real.** El campo `parameters` de una
 * `functionDeclaration` es un subconjunto de OpenAPI 3.0 y NO admite
 * `additionalProperties`. En la versión de escritorio (Python) del proyecto,
 * todas las herramientas lo declaraban — que es lo correcto para validar los
 * argumentos en local — y el resultado fue que Gemini rechazaba el 100 % de los
 * turnos de conversación con:
 *
 *     HTTP 400: Invalid JSON payload received. Unknown name "additionalProperties"
 *     at 'tools[0].function_declarations[0].parameters': Cannot find field.
 *
 * Aquí se limpia el esquema justo antes de enviarlo, sin tocar el original (el
 * mismo esquema sigue validando en local, donde sí interesa que sea estricto).
 * Los tests cubren el caso exacto.
 */
object ToolSchema {

    /** Palabras clave que Gemini no reconoce y que provocan un 400. */
    private val UNSUPPORTED = setOf(
        "additionalProperties",
        "\$schema",
        "\$id",
        "\$comment",
        "\$anchor",
        "\$defs",
        "definitions",
        "patternProperties",
        "unevaluatedProperties",
        "propertyNames",
        "dependentRequired",
        "dependentSchemas",
        "dependencies",
        "if",
        "then",
        "else",
        "not",
        "examples",
    )

    /** Claves cuyo valor es a su vez un esquema. */
    private val SCHEMA_KEYS = setOf("items", "additionalItems", "contains")

    /** Claves cuyo valor es una lista de esquemas. */
    private val SCHEMA_LIST_KEYS = setOf("anyOf", "allOf", "oneOf", "prefixItems")

    /** Devuelve una copia limpia del esquema. El original no se muta. */
    fun sanitize(element: JsonElement): JsonElement {
        if (element is JsonArray) {
            return JsonArray(element.map { sanitize(it) })
        }
        if (element !is JsonObject) return element

        val out = LinkedHashMap<String, JsonElement>()
        for ((key, value) in element) {
            if (key in UNSUPPORTED) continue
            when {
                // Gemini no tiene `const`; un enum de un solo valor dice lo mismo.
                key == "const" -> out["enum"] = JsonArray(listOf(value))

                // Gemini no acepta `type` como lista: ["string","null"] ->
                // type: "string" + nullable: true.
                key == "type" && value is JsonArray -> {
                    val nonNull = value.filterNot { it is JsonPrimitive && it.content == "null" }
                    if (value.any { it is JsonPrimitive && it.content == "null" }) {
                        out["nullable"] = JsonPrimitive(true)
                    }
                    if (nonNull.size == 1) out["type"] = nonNull[0]
                    // Con varios tipos reales no hay equivalente: se omite `type`
                    // antes que inventarse un `anyOf` que puede no encajar.
                }

                key == "properties" && value is JsonObject ->
                    out[key] = JsonObject(value.mapValues { sanitize(it.value) })

                key in SCHEMA_KEYS -> out[key] = sanitize(value)

                key in SCHEMA_LIST_KEYS && value is JsonArray ->
                    out[key] = JsonArray(value.map { sanitize(it) })

                else -> out[key] = value
            }
        }
        return JsonObject(out)
    }

    /** Recorre el esquema y devuelve las claves problemáticas que encuentre. */
    fun findUnsupportedKeys(element: JsonElement): Set<String> {
        val found = mutableSetOf<String>()
        fun walk(node: JsonElement, insideProperties: Boolean) {
            when (node) {
                is JsonObject ->
                    node.forEach { (key, value) ->
                        if (key == "properties" && value is JsonObject) {
                            value.values.forEach { walk(it, true) }
                        } else {
                            // Los nombres DENTRO de `properties` son nombres de
                            // argumentos del usuario, no palabras clave: no se juzgan.
                            if (key in UNSUPPORTED) found.add(key)
                            walk(value, insideProperties)
                        }
                    }

                is JsonArray -> node.forEach { walk(it, insideProperties) }
                else -> Unit
            }
        }
        walk(element, false)
        return found
    }
}
