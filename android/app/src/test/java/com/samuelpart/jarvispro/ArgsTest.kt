package com.samuelpart.jarvispro

import com.samuelpart.jarvispro.agent.Args
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * El modelo propone argumentos con tipos inconsistentes: números como texto,
 * booleanos como "sí". Estos tests fijan el comportamiento tolerante, porque un
 * `ClassCastException` aquí tumbaría la conversación entera.
 */
class ArgsTest {

    @Test
    fun `lee numeros que llegan como texto`() {
        val args = buildJsonObject { put("porcentaje", "70") }

        assertEquals(70, Args.int(args, "porcentaje"))
    }

    @Test
    fun `lee numeros que llegan como numero`() {
        val args = buildJsonObject { put("porcentaje", 70) }

        assertEquals(70, Args.int(args, "porcentaje"))
    }

    @Test
    fun `lee numeros con decimales y los trunca`() {
        val args = buildJsonObject { put("porcentaje", 69.7) }

        assertEquals(69, Args.int(args, "porcentaje"))
    }

    @Test
    fun `devuelve el valor por defecto si falta el argumento`() {
        val args = buildJsonObject { }

        assertEquals(25, Args.int(args, "porcentaje", 25))
        assertNull(Args.intOrNull(args, "porcentaje"))
    }

    @Test
    fun `devuelve el valor por defecto si el argumento no es un numero`() {
        val args = buildJsonObject { put("porcentaje", "alto") }

        assertEquals(25, Args.int(args, "porcentaje", 25))
    }

    @Test
    fun `entiende booleanos escritos de muchas maneras`() {
        listOf("true", "1", "si", "sí", "yes", "on", "encender").forEach { raw ->
            val args = buildJsonObject { put("encender", raw) }
            assertEquals("«$raw» debería ser true", true, Args.bool(args, "encender"))
        }

        listOf("false", "0", "no", "off", "apagar").forEach { raw ->
            val args = buildJsonObject { put("encender", raw) }
            assertEquals("«$raw» debería ser false", false, Args.bool(args, "encender"))
        }
    }

    @Test
    fun `entiende booleanos de verdad`() {
        assertTrue(Args.bool(buildJsonObject { put("encender", true) }, "encender"))
        assertEquals(false, Args.bool(buildJsonObject { put("encender", false) }, "encender"))
    }

    @Test
    fun `un booleano irreconocible no se inventa nada`() {
        val args = buildJsonObject { put("encender", "quizá") }

        assertNull(Args.boolOrNull(args, "encender"))
        assertEquals(true, Args.bool(args, "encender", default = true))
    }

    @Test
    fun `lee textos y detecta los vacios`() {
        val args = buildJsonObject { put("app", "whatsapp"); put("nota", "  ") }

        assertEquals("whatsapp", Args.str(args, "app"))
        assertEquals("sin valor", Args.str(args, "otra", "sin valor"))
        assertTrue(Args.isBlank(args, "nota"))
        assertTrue(Args.isBlank(args, "inexistente"))
    }

    @Test
    fun `construye respuestas con tipos correctos`() {
        val response = Args.response(
            "ok" to Args.flag(true),
            "nivel" to Args.number(70),
            "nombre" to Args.text("volumen"),
        )

        assertEquals(true, (response["ok"] as JsonPrimitive).content.toBoolean())
        assertEquals(70, (response["nivel"] as JsonPrimitive).content.toInt())
        assertEquals("volumen", (response["nombre"] as JsonPrimitive).content)
    }
}
