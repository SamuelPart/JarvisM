package com.samuelpart.jarvispro

import com.samuelpart.jarvispro.data.StoredMessage
import kotlinx.serialization.builtins.ListSerializer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * El historial se guarda en disco, así que su formato es un contrato: estos tests
 * evitan que un cambio de clase deje a los usuarios sin poder abrir su conversación.
 */
class HistorySerializationTest {

    private val serializer = ListSerializer(StoredMessage.serializer())

    @Test
    fun `ida y vuelta del historial`() {
        val messages = listOf(
            StoredMessage(StoredMessage.ROLE_USER, "enciende la linterna", timestamp = 1L),
            StoredMessage(
                role = StoredMessage.ROLE_TOOL,
                text = "Linterna encendida.",
                toolName = "flashlight",
                tier = "T1",
                ok = true,
                timestamp = 2L,
            ),
            StoredMessage(StoredMessage.ROLE_JARVIS, "Hecho.", timestamp = 3L),
        )

        val json = JarvisJson.encodeToString(serializer, messages)
        val back = JarvisJson.decodeFromString(serializer, json)

        assertEquals(messages, back)
    }

    @Test
    fun `los campos opcionales no se escriben si son nulos`() {
        val json = JarvisJson.encodeToString(
            serializer,
            listOf(StoredMessage(StoredMessage.ROLE_USER, "hola")),
        )

        // Formato compacto: nada de "toolName":null ocupando sitio.
        assertTrue(json.contains("\"role\":\"user\""))
        assertTrue("no debería aparecer toolName", !json.contains("toolName"))
    }

    @Test
    fun `un fichero con campos nuevos desconocidos sigue cargando`() {
        // Simula un historial guardado por una versión futura de la app.
        val json = """
            [{"role":"jarvis","text":"hola","campoNuevoDelFuturo":42}]
        """.trimIndent()

        val messages = JarvisJson.decodeFromString(serializer, json)

        assertEquals(1, messages.size)
        assertEquals("hola", messages[0].text)
    }

    @Test
    fun `un rol desconocido no revienta la carga`() {
        val json = """[{"role":"sistema_raro","text":"algo"}]"""

        val messages = JarvisJson.decodeFromString(serializer, json)

        assertEquals("sistema_raro", messages[0].role)
        assertEquals("algo", messages[0].text)
    }
}
