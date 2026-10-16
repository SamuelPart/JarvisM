package com.samuelpart.jarvispro

import com.samuelpart.jarvispro.gemini.ToolSchema
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Gemini no acepta `additionalProperties` en los esquemas de parámetros de sus
 * herramientas. Estos tests comprueban que la app elimine esa clave y mantenga
 * las demás conversiones compatibles con la API.
 */
class ToolSchemaTest {

    @Test
    fun `quita additionalProperties del nivel superior`() {
        val schema = buildJsonObject {
            put("type", "object")
            put("additionalProperties", false)
            put("properties", buildJsonObject {
                put("app", buildJsonObject { put("type", "string") })
            })
        }

        val clean = ToolSchema.sanitize(schema) as JsonObject

        assertNull("additionalProperties NO puede llegar a la API", clean["additionalProperties"])
        assertEquals("object", (clean["type"] as JsonPrimitive).content)
        assertNotNull(clean["properties"])
    }

    @Test
    fun `quita additionalProperties anidado dentro de properties`() {
        val schema = buildJsonObject {
            put("type", "object")
            put("properties", buildJsonObject {
                put("filtros", buildJsonObject {
                    put("type", "object")
                    put("additionalProperties", buildJsonObject { put("type", "string") })
                    put("properties", buildJsonObject {
                        put("orden", buildJsonObject { put("type", "string") })
                    })
                })
            })
        }

        val clean = ToolSchema.sanitize(schema) as JsonObject
        val nested = ((clean["properties"] as JsonObject)["filtros"] as JsonObject)

        assertNull(nested["additionalProperties"])
        // Lo que sí era válido sigue ahí.
        assertNotNull((nested["properties"] as JsonObject)["orden"])
    }

    @Test
    fun `no muta el esquema original`() {
        val original = buildJsonObject {
            put("type", "object")
            put("additionalProperties", false)
        }

        ToolSchema.sanitize(original)

        assertNotNull("el original debe conservar sus claves", original["additionalProperties"])
    }

    @Test
    fun `convierte const en enum de un solo valor`() {
        val schema = buildJsonObject {
            put("type", "object")
            put("properties", buildJsonObject {
                put("modo", buildJsonObject { put("const", "silencioso") })
            })
        }

        val clean = ToolSchema.sanitize(schema) as JsonObject
        val modo = ((clean["properties"] as JsonObject)["modo"] as JsonObject)

        assertNull(modo["const"])
        val enum = modo["enum"] as JsonArray
        assertEquals(1, enum.size)
        assertEquals("silencioso", (enum[0] as JsonPrimitive).content)
    }

    @Test
    fun `type con null pasa a nullable`() {
        val schema = buildJsonObject {
            put("type", "object")
            put("properties", buildJsonObject {
                put("hora", buildJsonObject { put("type", buildJsonArray { add("string"); add("null") }) })
            })
        }

        val clean = ToolSchema.sanitize(schema) as JsonObject
        val hora = ((clean["properties"] as JsonObject)["hora"] as JsonObject)

        assertEquals("string", (hora["type"] as JsonPrimitive).content)
        assertEquals("true", (hora["nullable"] as JsonPrimitive).content)
    }

    @Test
    fun `limpia arrays de esquemas como items y anyOf`() {
        val schema = buildJsonObject {
            put("type", "object")
            put("properties", buildJsonObject {
                put("opciones", buildJsonObject {
                    put("type", "array")
                    put("items", buildJsonObject {
                        put("type", "string")
                        put("additionalProperties", false)
                    })
                })
                put("cualquiera", buildJsonObject {
                    put("anyOf", buildJsonArray {
                        add(buildJsonObject { put("type", "string"); put("additionalProperties", false) })
                        add(buildJsonObject { put("type", "integer") })
                    })
                })
            })
        }

        val clean = ToolSchema.sanitize(schema) as JsonObject
        val props = clean["properties"] as JsonObject
        val items = ((props["opciones"] as JsonObject)["items"] as JsonObject)
        assertNull(items["additionalProperties"])

        val anyOf = ((props["cualquiera"] as JsonObject)["anyOf"] as JsonArray)
        assertEquals(2, anyOf.size)
        assertNull((anyOf[0] as JsonObject)["additionalProperties"])
    }

    @Test
    fun `quita claves de JSON Schema que la API no conoce`() {
        val schema = buildJsonObject {
            put("\$schema", "https://json-schema.org/draft/2020-12/schema")
            put("\$id", "esquema")
            put("definitions", buildJsonObject { })
            put("examples", buildJsonArray { add(JsonPrimitive("algo")) })
            put("type", "object")
        }

        val clean = ToolSchema.sanitize(schema) as JsonObject

        listOf("\$schema", "\$id", "definitions", "examples").forEach { key ->
            assertNull("«$key» debería haberse quitado", clean[key])
        }
    }

    @Test
    fun `detecta las claves invalidas que quedarian en un esquema sin sanear`() {
        val schema = buildJsonObject {
            put("type", "object")
            put("additionalProperties", false)
            put("properties", buildJsonObject {
                put("nombre", buildJsonObject {
                    put("type", "string")
                    // Un argumento que se LLAMA igual que una palabra clave: es un
                    // nombre legítimo y no debe marcarse como problema.
                    put("properties", buildJsonObject {
                        put("additionalProperties", buildJsonObject { put("type", "string") })
                    })
                })
            })
        }

        val found = ToolSchema.findUnsupportedKeys(schema)

        assertTrue("debería ver el additionalProperties del nivel superior", "additionalProperties" in found)
    }

    @Test
    fun `un esquema ya limpio no se rompe al volver a pasarlo`() {
        val schema = buildJsonObject {
            put("type", "object")
            put("properties", buildJsonObject {
                put("accion", buildJsonObject {
                    put("type", "string")
                    put("enum", buildJsonArray { add("subir"); add("bajar") })
                })
            })
            put("required", buildJsonArray { add("accion") })
        }

        val once = ToolSchema.sanitize(schema)
        val twice = ToolSchema.sanitize(once)

        // El saneado es idempotente: aplicarlo dos veces da lo mismo.
        assertEquals(once.toString(), twice.toString())
    }

    @Test
    fun `las claves no reconocidas no se confunden con nombres de argumentos`() {
        val schema = buildJsonObject {
            put("type", "object")
            put("properties", buildJsonObject {
                put("const", buildJsonObject { put("type", "string") }) // argumento llamado "const"
            })
        }

        val clean = ToolSchema.sanitize(schema) as JsonObject
        val props = clean["properties"] as JsonObject

        assertNotNull("un argumento llamado «const» debe sobrevivir", props["const"])
        assertFalse(props.containsKey("enum"))
    }
}
