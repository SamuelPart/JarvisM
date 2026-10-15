package com.samuelpart.jarvispro.voice

import android.content.Context
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import java.util.Locale

/**
 * Lectura de las respuestas en voz alta (motor TTS del teléfono).
 *
 * Detalle que importa: antes de hablar se limpia la cola (`QUEUE_FLUSH`). Si el
 * usuario manda otro mensaje mientras Jarvis habla, la frase anterior se corta en
 * vez de encolarse y soltar un monólogo desfasado.
 */
class Speaker(context: Context) {

    private var tts: TextToSpeech? = null
    private var ready = false
    private var pendingText: String? = null

    init {
        tts = TextToSpeech(context.applicationContext) { status ->
            ready = status == TextToSpeech.SUCCESS
            if (ready) {
                // Locale español; si el motor no lo tiene, se deja el que use por
                // defecto en vez de fallar (algunos motores solo traen en-US).
                runCatching { tts?.language = Locale("es", "ES") }
                runCatching {
                    tts?.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                        override fun onStart(utteranceId: String?) = Unit
                        override fun onDone(utteranceId: String?) = Unit
                        @Deprecated("Método heredado del API antiguo")
                        override fun onError(utteranceId: String?) = Unit
                    })
                }
                pendingText?.let { text ->
                    pendingText = null
                    speak(text)
                }
            }
        }
    }

    /** Lee el texto. Si el motor aún no está listo, se guarda y se lee al arrancar. */
    fun speak(text: String) {
        val clean = cleanForSpeech(text)
        if (clean.isBlank()) return
        if (!ready) {
            pendingText = clean
            return
        }
        runCatching {
            tts?.speak(clean, TextToSpeech.QUEUE_FLUSH, null, UTTERANCE_ID)
        }
    }

    fun stop() {
        runCatching { tts?.stop() }
    }

    fun shutdown() {
        runCatching { tts?.stop() }
        runCatching { tts?.shutdown() }
        tts = null
        ready = false
    }

    /**
     * Quita lo que suena mal leído en voz alta: viñetas, almohadillas, asteriscos
     * de markdown y bloques de código (que además serían larguísimos).
     */
    private fun cleanForSpeech(text: String): String {
        var out = text
        out = out.replace(Regex("```[\\s\\S]*?```"), " (te dejo el código en pantalla) ")
        out = out.replace(Regex("`([^`]*)`"), "$1")
        out = out.replace(Regex("(?m)^\\s*[-*•]\\s*"), "")
        out = out.replace(Regex("(?m)^\\s*#+\\s*"), "")
        out = out.replace(Regex("[*_#]+"), "")
        out = out.replace(Regex("\\[(.*?)]\\((.*?)\\)"), "$1")
        out = out.replace(Regex("\\n{2,}"), ". ")
        out = out.replace('\n', ' ')
        return out.trim()
    }

    private companion object {
        const val UTTERANCE_ID = "jarvis-response"
    }
}
