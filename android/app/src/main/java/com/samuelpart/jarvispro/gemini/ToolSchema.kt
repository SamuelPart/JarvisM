package com.samuelpart.jarvispro.gemini

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Adapta JSON Schemas al subconjunto que acepta la API de Gemini.
 *
 * El campo `parameters` de una `functionDeclaration` acepta solo un subconjunto
 * de JSON Schema y no admite `additionalProperties`. Si se incluye esa clave, la
 * API de Gemini rechaza la petición con HTTP 400.
 *
 * Se eliminan las claves no compatibles justo antes de enviar la petición, sin
 * modificar las declaraciones originales de las herramientas. Los tests cubren
 * el caso y las demás conversiones necesarias.
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
