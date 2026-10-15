package com.samuelpart.jarvispro.gemini

import com.samuelpart.jarvispro.JarvisJson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.coroutineContext

/** Error de la API ya traducido a algo que un humano pueda entender. */
class GeminiException(
    val status: Int,
    override val message: String,
    val model: String = "",
) : Exception(message)

/**
 * Cliente HTTP de la API de Gemini.
 *
 * Se usa OkHttp directamente en vez del SDK oficial por lo explicado en
 * `GeminiDtos.kt`. Los detalles que importan:
 *
 * - Auth por cabecera `x-goog-api-key`. Las claves nuevas de AI Studio empiezan
 *   por `AQ.Ab…` (auth keys) y SOLO funcionan por cabecera: por parámetro `?key=`
 *   fallan. Las antiguas (`AIza…`) también funcionan así.
 * - Streaming por `:streamGenerateContent?alt=sse`, leído línea a línea. Nada de
 *   cargar la respuesta entera en memoria.
 * - Los errores 4xx/5xx se convierten en `GeminiException` con un mensaje útil,
 *   incluido el modelo que se envió (sin eso, un 404 es una adivinanza).
 */
class GeminiClient(
    private val json: Json = JarvisJson,
    private val http: OkHttpClient = defaultHttpClient(),
) {

    suspend fun generate(
        request: GeminiRequest,
        apiKey: String,
        model: String,
    ): GeminiResponse = withContext(Dispatchers.IO) {
        val body = json.encodeToString(GeminiRequest.serializer(), request)
        val call = http.newCall(
            Request.Builder()
                .url("$BASE_URL/models/$model:generateContent")
                .addHeader("x-goog-api-key", apiKey)
                .addHeader("Content-Type", "application/json")
                .post(body.toRequestBody(JSON_MEDIA))
                .build(),
        )
        try {
            call.execute().use { response ->
                val text = response.body?.string().orEmpty()
                if (!response.isSuccessful) throw errorFor(response.code, text, model)
                json.decodeFromString(GeminiResponse.serializer(), text)
            }
        } catch (io: IOException) {
            throw GeminiException(0, networkMessage(io), model)
        }
    }

    /**
     * Streaming SSE. Devuelve el texto acumulado al terminar.
     *
     * `onDelta` se invoca desde el hilo de IO; quien lo use debe saltar al hilo
     * principal si toca la interfaz.
     */
    suspend fun stream(
        request: GeminiRequest,
        apiKey: String,
        model: String,
        onDelta: suspend (StreamDelta) -> Unit,
    ): String = withContext(Dispatchers.IO) {
        val body = json.encodeToString(GeminiRequest.serializer(), request)
        val call = http.newCall(
            Request.Builder()
                .url("$BASE_URL/models/$model:streamGenerateContent?alt=sse")
                .addHeader("x-goog-api-key", apiKey)
                .addHeader("Content-Type", "application/json")
                .addHeader("Accept", "text/event-stream")
                .post(body.toRequestBody(JSON_MEDIA))
                .build(),
        )
        val collected = StringBuilder()
        try {
            call.execute().use { response ->
                if (!response.isSuccessful) {
                    throw errorFor(response.code, response.body?.string().orEmpty(), model)
                }
                val source = response.body?.source()
                    ?: throw GeminiException(response.code, "Respuesta vacía del servidor.", model)

                val events = SseEventBuffer()
                while (true) {
                    // Corta de inmediato si el usuario pulsó "Detener".
                    coroutineContext.ensureActive()
                    val line = source.readUtf8Line() ?: break
                    val payload = events.push(line) ?: continue

                    val delta = StreamDecoder.decode(payload, json)
                    delta.error?.let { apiError ->
                        throw GeminiException(
                            apiError.code,
                            apiError.message.ifBlank { "Error de la API durante el streaming." },
                            model,
                        )
                    }
                    if (delta.text.isNotEmpty()) collected.append(delta.text)
                    if (delta.text.isNotEmpty() || delta.calls.isNotEmpty() || delta.usage != null) {
                        onDelta(delta)
                    }
                }
            }
        } catch (io: IOException) {
            // Si ya llegó texto, no se tira: es mejor mostrar lo que hay que perderlo.
            if (collected.isEmpty()) throw GeminiException(0, networkMessage(io), model)
        }
        collected.toString()
    }

    /** Modelos que la cuenta puede usar de verdad, según la propia API. */
    suspend fun listModels(apiKey: String): List<String> = withContext(Dispatchers.IO) {
        val call = http.newCall(
            Request.Builder()
                .url("$BASE_URL/models?pageSize=200")
                .addHeader("x-goog-api-key", apiKey)
                .get()
                .build(),
        )
        try {
            call.execute().use { response ->
                val text = response.body?.string().orEmpty()
                if (!response.isSuccessful) throw errorFor(response.code, text, "")
                json.decodeFromString(ModelsListResponse.serializer(), text)
                    .models
                    .filter { model ->
                        model.supportedGenerationMethods.isEmpty() ||
                            model.supportedGenerationMethods.any { it == "generateContent" }
                    }
                    .map { it.shortName }
                    .filterNot { it.contains("embedding") || it.contains("aqa") || it.contains("imagen") }
            }
        } catch (io: IOException) {
            throw GeminiException(0, networkMessage(io), "")
        }
    }

    /** Comprobación rápida para el botón "Probar conexión" de los Ajustes. */
    suspend fun ping(apiKey: String, model: String): String {
        val response = generate(
            GeminiRequest(
                contents = listOf(Content(role = "user", parts = listOf(Part(text = "ping")))),
                generationConfig = GenerationConfig(maxOutputTokens = 16),
            ),
            apiKey = apiKey,
            model = model,
        )
        return response.candidates.firstOrNull()?.content?.parts
            ?.mapNotNull { it.text }
            ?.joinToString("")
            .orEmpty()
    }

    // -- errores ----------------------------------------------------------- //

    private fun networkMessage(io: IOException): String =
        "No se pudo contactar con la API (${io.javaClass.simpleName}: ${io.message}). " +
            "Comprueba tu conexión a internet o el modo avión."

    private fun errorFor(code: Int, body: String, model: String): GeminiException {
        val apiMessage = runCatching {
            json.decodeFromString(ApiErrorBody.serializer(), body).error?.message
        }.getOrNull()
        val detail = apiMessage ?: body.take(300)

        val friendly = when (code) {
            400 -> buildString {
                append("La API rechazó la petición (400): ")
                append(detail)
                // Traducción de la causa más probable, aprendida a golpes.
                if (body.contains("additionalProperties")) {
                    append(
                        "\n\nPista: es el schema de herramientas. La app ya debería " +
                            "limpiarlo; si ves esto, avisa: es un bug.",
                    )
                } else if (body.contains("thought", ignoreCase = true)) {
                    append("\n\nPista: firma de pensamiento perdida entre turnos.")
                }
            }

            401, 403 -> "Clave de API rechazada ($code). Revisa la clave en Ajustes y que " +
                "esté activa en aistudio.google.com. Detalle: $detail"

            404 -> "El modelo «$model» no está disponible para tu clave ($code). " +
                "Usa «Ver modelos disponibles» en Ajustes y elige uno de la lista."

            429 -> "Límite de peticiones o cuota agotada (429). Espera un minuto o " +
                "prueba un modelo «flash-lite», que tiene cuota más amplia."

            in 500..599 -> "Fallo del servicio de Google ($code). Reintenta en unos segundos."

            else -> "Error HTTP $code: $detail"
        }
        return GeminiException(code, friendly, model)
    }

    companion object {
        const val BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
        private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()

        /**
         * Tiempos pensados para streaming: el `readTimeout` es largo porque una
         * respuesta con razonamiento puede tardar, y cortarlo a los 30 s daría
         * "timeout" en respuestas perfectamente normales.
         */
        fun defaultHttpClient(): OkHttpClient = OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(180, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .callTimeout(240, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()
    }
}
