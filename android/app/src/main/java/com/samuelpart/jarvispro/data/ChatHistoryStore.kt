package com.samuelpart.jarvispro.data

import android.content.Context
import com.samuelpart.jarvispro.JarvisJson
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import java.io.File

/**
 * Un mensaje tal y como se guarda en disco.
 *
 * Se usa una clase plana con `role` en texto (en vez de una jerarquía sellada)
 * porque el formato en disco debe poder leerse aunque la app cambie: un fichero
 * viejo con un rol desconocido se muestra como texto, no rompe la carga.
 */
@Serializable
data class StoredMessage(
    val role: String,
    val text: String,
    val toolName: String? = null,
    val tier: String? = null,
    val ok: Boolean = true,
    val timestamp: Long = 0L,
) {
    companion object {
        const val ROLE_USER = "user"
        const val ROLE_JARVIS = "jarvis"
        const val ROLE_TOOL = "tool"
        const val ROLE_ERROR = "error"
        const val ROLE_NOTICE = "notice"
    }
}

/**
 * Historial de conversación en un fichero JSON dentro del almacén privado.
 *
 * Se limita a [MAX_MESSAGES] mensajes: la API recibe todo el historial en cada
 * petición, así que un historial eterno encarecería cada turno hasta agotar la
 * cuota gratuita. Los mensajes viejos se descartan por el principio.
 */
class ChatHistoryStore(context: Context, private val json: Json = JarvisJson) {

    private val file = File(context.applicationContext.filesDir, FILE_NAME)

    fun load(): List<StoredMessage> {
        if (!file.exists()) return emptyList()
        return try {
            val text = file.readText()
            if (text.isBlank()) emptyList()
            else json.decodeFromString(ListSerializer, text)
        } catch (_: Exception) {
            // Un historial corrupto no puede impedir abrir la app: se empieza de cero.
            emptyList()
        }
    }

    fun save(messages: List<StoredMessage>) {
        try {
            val trimmed = if (messages.size > MAX_MESSAGES) messages.takeLast(MAX_MESSAGES) else messages
            file.writeText(json.encodeToString(ListSerializer, trimmed))
        } catch (_: Exception) {
            // Sin espacio o sin permisos: se pierde el historial, no la sesión.
        }
    }

    fun clear() {
        runCatching { if (file.exists()) file.delete() }
    }

    private companion object {
        const val FILE_NAME = "historial.json"
        const val MAX_MESSAGES = 200
        val ListSerializer = kotlinx.serialization.builtins.ListSerializer(StoredMessage.serializer())
    }
}
