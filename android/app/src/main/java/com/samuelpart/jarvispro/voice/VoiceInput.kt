package com.samuelpart.jarvispro.voice

import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer

/**
 * Dictado por voz usando el reconocedor del propio teléfono.
 *
 * Se usa `SpeechRecognizer` (el de Android) y no la API de audio de Gemini por una
 * razón práctica: es gratis, funciona sin conexión en muchos móviles y se integra
 * con el micrófono del sistema sin pedir la clave otra vez. La voz natural
 * bidireccional con Gemini Live es la Fase 2 (ver PLAN-APP.md).
 *
 * **Todo aquí debe ejecutarse en el hilo principal**: `SpeechRecognizer` no es
 * seguro desde otros hilos, y por eso la app lo llama siempre desde la interfaz.
 */
class VoiceInput(private val context: Context) {

    private var recognizer: SpeechRecognizer? = null

    fun isAvailable(): Boolean = SpeechRecognizer.isRecognitionAvailable(context)

    fun start(
        language: String,
        onPartial: (String) -> Unit,
        onFinal: (String) -> Unit,
        onError: (String) -> Unit,
    ) {
        if (!isAvailable()) {
            onError("Este teléfono no tiene servicio de reconocimiento de voz. " +
                "Instala «Google» desde Play Store y vuelve a intentarlo.")
            return
        }

        if (recognizer == null) {
            recognizer = SpeechRecognizer.createSpeechRecognizer(context).apply {
                setRecognitionListener(object : RecognitionListener {
                    override fun onReadyForSpeech(params: Bundle?) = Unit
                    override fun onBeginningOfSpeech() = Unit
                    override fun onRmsChanged(rmsdB: Float) = Unit
                    override fun onBufferReceived(buffer: ByteArray?) = Unit
                    override fun onEndOfSpeech() = Unit
                    override fun onEvent(eventType: Int, params: Bundle?) = Unit

                    override fun onError(error: Int) {
                        // ERROR_NO_MATCH y ERROR_SPEECH_TIMEOUT pasan muy a menudo
                        // (silencio, ruido): se avisa en suave y no es un fallo real.
                        onError(mapError(error))
                    }

                    override fun onResults(results: Bundle?) {
                        val text = results.bestText()
                        if (text.isBlank()) onError("No te entendí. Prueba otra vez.")
                        else onFinal(text)
                    }

                    override fun onPartialResults(partialResults: Bundle?) {
                        partialResults.bestText().takeIf { it.isNotBlank() }?.let(onPartial)
                    }
                })
            }
        }

        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
            putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            putExtra(RecognizerIntent.EXTRA_LANGUAGE, language)
            // Resultados parciales: el texto aparece mientras hablas, que es lo que
            // hace que se sienta un asistente y no un formulario.
            putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
            putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, context.packageName)
        }

        runCatching { recognizer?.startListening(intent) }
            .onFailure { onError("No pude abrir el micrófono.") }
    }

    fun stop() {
        runCatching { recognizer?.stopListening() }
    }

    fun cancel() {
        runCatching { recognizer?.cancel() }
    }

    /** Se llama desde `onCleared` del ViewModel: libera el servicio de voz. */
    fun destroy() {
        runCatching { recognizer?.destroy() }
        recognizer = null
    }

    private fun Bundle?.bestText(): String =
        this?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
            ?.firstOrNull()
            .orEmpty()

    private fun mapError(error: Int): String = when (error) {
        SpeechRecognizer.ERROR_NO_MATCH,
        SpeechRecognizer.ERROR_SPEECH_TIMEOUT,
        -> "No te entendí. ¿Lo repites?"

        SpeechRecognizer.ERROR_AUDIO -> "Hubo un problema con el micrófono."
        SpeechRecognizer.ERROR_NETWORK,
        SpeechRecognizer.ERROR_NETWORK_TIMEOUT,
        -> "El reconocimiento de voz necesita conexión y no la encontró."

        SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS ->
            "Falta el permiso de micrófono. Concédelo en Ajustes de la app."

        SpeechRecognizer.ERROR_RECOGNIZER_BUSY ->
            "El reconocedor está ocupado. Espera un segundo y vuelve a intentarlo."

        SpeechRecognizer.ERROR_CLIENT -> "" // Cancelación propia: no hay nada que decir.
        else -> "No pude usar el micrófono (código $error)."
    }
}
