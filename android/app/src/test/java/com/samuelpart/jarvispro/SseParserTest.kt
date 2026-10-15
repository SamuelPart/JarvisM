package com.samuelpart.jarvispro

import com.samuelpart.jarvispro.gemini.SseEventBuffer
import com.samuelpart.jarvispro.gemini.StreamDecoder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** El parser del stream SSE: se prueba con eventos reales de la API de Gemini. */
class SseParserTest {

    @Test
    fun `emite el payload al llegar la linea vacia`() {
        val buffer = SseEventBuffer()

        assertNull("la línea data sola todavía no cierra el evento", buffer.push("data: {\"a\":1}"))
        // La línea EN BLANCO es la que cierra el evento y devuelve el payload.
        assertEquals("{\"a\":1}", buffer.push(""))
        assertNull("sin nada pendiente, la línea vacía no produce evento", buffer.push(""))
    }

    @Test
    fun `junta varias lineas data en un solo payload`() {
        val buffer = SseEventBuffer()
        buffer.push("data: primera")
        buffer.push("data: segunda")
        val payload = buffer.push("")

        assertEquals("primera\nsegunda", payload)
    }

    @Test
    fun `ignora comentarios y keep-alives`() {
        val buffer = SseEventBuffer()

        assertNull(buffer.push(": keep-alive"))
        assertNull(buffer.push(""))
        // Un comentario suelto no debe producir un evento vacío.
        assertNull(buffer.push(""))
    }

    @Test
    fun `tolera finales de linea de windows`() {
        val buffer = SseEventBuffer()
        buffer.push("data: hola\r")
        assertEquals("hola", buffer.push(""))
    }

    @Test
    fun `decodifica texto de una respuesta`() {
        val payload = """
            {"candidates":[{"content":{"role":"model","parts":[{"text":"Buenas tardes"}]}}]}
        """.trimIndent()

        val delta = StreamDecoder.decode(payload)

        assertEquals("Buenas tardes", delta.text)
        assertTrue(delta.calls.isEmpty())
    }

    @Test
    fun `decodifica varios fragments de texto seguidos`() {
        val first = StreamDecoder.decode(
            """{"candidates":[{"content":{"parts":[{"text":"Hola"}]}}]}""",
        )
        val second = StreamDecoder.decode(
            """{"candidates":[{"content":{"parts":[{"text":", señor"}]}}]}""",
        )

        assertEquals("Hola", first.text)
        assertEquals(", señor", second.text)
    }

    @Test
    fun `decodifica una llamada a funcion y conserva su firma`() {
        val payload = """
            {"candidates":[{"content":{"role":"model","parts":[{
              "functionCall":{"name":"flashlight","args":{"encender":true}},
              "thoughtSignature":"ZmlybWEtbG9uZ2E="
            }]}}]}
        """.trimIndent()

        val delta = StreamDecoder.decode(payload)

        assertEquals(1, delta.calls.size)
        assertEquals("flashlight", delta.calls[0].name)
        assertEquals("true", delta.calls[0].args?.get("encender").toString())

        // La firma de pensamiento debe sobrevivir en los parts: si se pierde, la
        // siguiente petición a Gemini 3 falla con 400.
        assertEquals(1, delta.parts.size)
        assertNotNull(delta.parts[0].thoughtSignature)
        assertEquals("ZmlybWEtbG9uZ2E=", delta.parts[0].thoughtSignature)
    }

    @Test
    fun `decodifica un error dentro del stream`() {
        val payload = """{"error":{"code":429,"message":"Quota exceeded","status":"RESOURCE_EXHAUSTED"}}"""

        val delta = StreamDecoder.decode(payload)

        assertNotNull(delta.error)
        assertEquals(429, delta.error?.code)
        assertEquals("Quota exceeded", delta.error?.message)
    }

    @Test
    fun `un evento ilegible no rompe el streaming`() {
        val delta = StreamDecoder.decode("{esto no es json")

        assertEquals("", delta.text)
        assertTrue(delta.calls.isEmpty())
        assertNull(delta.error)
    }

    @Test
    fun `ignora el centinela de fin de stream`() {
        val delta = StreamDecoder.decode("[DONE]")

        assertEquals("", delta.text)
        assertTrue(delta.calls.isEmpty())
    }

    @Test
    fun `recoge el motivo de fin y el uso de tokens`() {
        val payload = """
            {"candidates":[{"content":{"parts":[{"text":"ok"}]},"finishReason":"STOP"}],
             "usageMetadata":{"promptTokenCount":12,"candidatesTokenCount":3,"totalTokenCount":15}}
        """.trimIndent()

        val delta = StreamDecoder.decode(payload)

        assertEquals("STOP", delta.finishReason)
        assertEquals(15, delta.usage?.totalTokenCount)
    }

    @Test
    fun `recoge el bloqueo por seguridad`() {
        val payload = """{"promptFeedback":{"blockReason":"SAFETY"}}"""

        val delta = StreamDecoder.decode(payload)

        assertEquals("SAFETY", delta.blockReason)
    }

    @Test
    fun `un evento partido en varias lineas data se une antes de decodificar`() {
        val buffer = SseEventBuffer()
        buffer.push("data: {\"candidates\":[{\"content\":{\"parts\":[{\"text\":\"hola\"}]}}]}")

        val payload = buffer.push("")
        val delta = StreamDecoder.decode(payload ?: "")

        assertEquals("hola", delta.text)
    }
}
