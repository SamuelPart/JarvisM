package com.samuelpart.jarvispro.gemini

import com.samuelpart.jarvispro.JarvisJson
import kotlinx.serialization.SerializationException
import kotlinx.serialization.json.Json

/**
 * Acumulador de eventos SSE (Server-Sent Events).
 *
 * El protocolo agrupa líneas en eventos: las líneas `data:` se concatenan y el
 * evento se cierra con una línea vacía. Gemini manda un JSON por evento, pero se
 * implementa el protocolo completo (y no un simple `startsWith("data:")`) porque
 * un evento puede partirse en varias líneas y porque las líneas que empiezan por
 * `:` son comentarios/keep-alive que hay que ignorar sin romper nada.
 *
 * Es una clase pura: se puede probar sin Android y sin red.
 */
class SseEventBuffer {
    private val dataLines = mutableListOf<String>()

    /**
     * Alimenta UNA línea (sin el salto) y devuelve el payload si esa línea cierra
     * un evento; `null` si el evento sigue abierto.
     */
    fun push(line: String): String? {
        val clean = line.trimEnd('\r')
        if (clean.isEmpty()) {
            if (dataLines.isEmpty()) return null
            val payload = dataLines.joinToString("\n")
            dataLines.clear()
            return payload
        }
        if (clean.startsWith(":")) return null // comentario / keep-alive
        if (clean.startsWith("data:")) {
            dataLines.add(clean.substring(5).trimStart())
        }
        // Otros campos SSE (event:, id:, retry:) no los usa Gemini: se ignoran.
        return null
    }

    fun reset() = dataLines.clear()
}

/** Lo que aporta un evento del stream ya decodificado. */
data class StreamDelta(
    val text: String = "",
    val calls: List<FunctionCall> = emptyList(),
    /**
     * Los `parts` del modelo TAL CUAL llegaron.
     *
     * No es duplicar `calls`: cada `functionCall` de Gemini 3 llega acompañado de
     * un `thoughtSignature`, y la API exige recibirlo de vuelta en el turno
     * siguiente. Si se reconstruyen los parts a mano y se pierde la firma, la
     * siguiente petición falla con 400 "thought signature is missing". Por eso el
     * agente reenvía esta lista sin tocar.
     */
    val parts: List<Part> = emptyList(),
    val finishReason: String? = null,
    val usage: Usage? = null,
    val blockReason: String? = null,
    val error: ApiError? = null,
)

/**
 * Traduce el JSON de un evento SSE a algo que el agente entienda.
 *
 * Es una función pura (texto -> delta), así que los tests la cubren con streams
 * reales grabados, incluidos los troceados a mitad de línea.
 */
object StreamDecoder {

    fun decode(payload: String, json: Json = JarvisJson): StreamDelta {
        val trimmed = payload.trim()
        if (trimmed.isEmpty() || trimmed == "[DONE]") return StreamDelta()

        val response: GeminiResponse = try {
            json.decodeFromString(trimmed)
        } catch (_: SerializationException) {
            // Un evento que no es una respuesta completa suele ser un error suelto
            // (`{"error": {...}}`), que la API también envía dentro del stream.
            return try {
                StreamDelta(error = json.decodeFromString<ApiErrorBody>(trimmed).error)
            } catch (_: SerializationException) {
                StreamDelta()
            }
        }

        val text = StringBuilder()
        val calls = mutableListOf<FunctionCall>()
        val parts = mutableListOf<Part>()
        var finish: String? = null
        for (candidate in response.candidates) {
            candidate.content?.parts?.forEach { part ->
                part.text?.let { text.append(it) }
                part.functionCall?.let { calls.add(it) }
                parts.add(part)
            }
            candidate.finishReason?.let { finish = it }
        }

        return StreamDelta(
            text = text.toString(),
            calls = calls,
            parts = parts,
            finishReason = finish,
            usage = response.usageMetadata,
            blockReason = response.promptFeedback?.blockReason,
        )
    }
}
