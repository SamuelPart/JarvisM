package com.samuelpart.jarvispro.agent

import com.samuelpart.jarvispro.data.AppSettings
import com.samuelpart.jarvispro.gemini.Content
import com.samuelpart.jarvispro.gemini.FunctionCall
import com.samuelpart.jarvispro.gemini.FunctionResponse
import com.samuelpart.jarvispro.gemini.GeminiClient
import com.samuelpart.jarvispro.gemini.GeminiRequest
import com.samuelpart.jarvispro.gemini.GenerationConfig
import com.samuelpart.jarvispro.gemini.Part
import com.samuelpart.jarvispro.gemini.ToolsBlock
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/**
 * El bucle del agente: conversación con herramientas.
 *
 * Un turno puede necesitar varios viajes a la API:
 *
 *   1. Se envía la conversación + las herramientas habilitadas.
 *   2. El modelo responde hablando, o pidiendo ejecutar una herramienta (o las dos
 *      cosas: en Gemini 3 es normal que "piense en voz alta" y luego llame).
 *   3. Por cada herramienta: se decide con la política de riesgo si hace falta
 *      permiso; se ejecuta; se devuelve el resultado como `functionResponse`.
 *   4. Se repite hasta que el modelo responde sin pedir nada más.
 *
 * Dos reglas que no se pueden romper para que las llamadas a herramientas sean seguras:
 *
 *   - **Los `parts` del modelo se reenvían tal cual**, con sus firmas. Si se
 *     reconstruyen, Gemini 3 responde 400.
 *   - **Nunca se ejecuta una herramienta sin pasar por `Policy`**. La decisión se
 *     toma aquí, en un solo sitio, no dentro de cada herramienta.
 */
class JarvisAgent(
    private val client: GeminiClient,
    private val registry: ToolRegistry,
) {

    /** Pide permiso al usuario. Devuelve true si acepta. */
    fun interface Confirmer {
        suspend fun confirm(tool: Tool, args: JsonObject, tier: RiskTier): Boolean
    }

    /** Recibe los eventos del turno. */
    fun interface EventSink {
        suspend fun emit(event: AgentEvent)
    }

    /**
     * Ejecuta un turno completo.
     *
     * @param history contexto acumulado de la conversación. El agente lo amplía
     *   con este turno (mensaje del usuario, respuestas del modelo y resultados de
     *   las herramientas) para que el siguiente turno tenga memoria.
     * @return el texto final del asistente (vacío si solo hubo acciones).
     */
    suspend fun runTurn(
        settings: AppSettings,
        history: MutableList<Content>,
        userText: String,
        toolContext: ToolContext,
        confirmer: Confirmer,
        sink: EventSink,
    ): String {
        if (!settings.isConfigured) {
            sink.emit(AgentEvent.Notice("Falta la clave de la API de Gemini. Ábrela en Ajustes."))
            sink.emit(AgentEvent.Done(""))
            return ""
        }

        history.add(Content(role = "user", parts = listOf(Part(text = userText))))
        pruneHistory(history)

        val declarations = registry.declarations(settings)
        val tools = if (declarations.isEmpty()) null else listOf(ToolsBlock(declarations))
        val maxRounds = if (tools == null) 1 else MAX_TOOL_ROUNDS

        var lastText = ""
        for (round in 0 until maxRounds) {
            val request = GeminiRequest(
                contents = history.toList(),
                tools = tools,
                systemInstruction = Content(parts = listOf(Part(text = settings.systemPrompt))),
                generationConfig = GenerationConfig(
                    temperature = settings.temperature.toDouble(),
                    maxOutputTokens = settings.maxOutputTokens,
                ),
            )

            val modelParts = mutableListOf<Part>()
            val roundText = StringBuilder()
            var blocked: String? = null

            client.stream(request, settings.apiKey, settings.model) { delta ->
                delta.blockReason?.let { reason ->
                    blocked = "La respuesta se bloqueó por seguridad ($reason). " +
                        "Prueba a reformular la petición."
                }
                // Se acumulan los parts ORIGINALES (con firmas): ver la nota de arriba.
                modelParts.addAll(delta.parts)
                if (delta.text.isNotEmpty()) {
                    roundText.append(delta.text)
                    sink.emit(AgentEvent.Text(delta.text))
                }
            }

            if (blocked != null) {
                sink.emit(AgentEvent.Notice(blocked))
                sink.emit(AgentEvent.Done(""))
                return ""
            }

            if (modelParts.isNotEmpty()) {
                history.add(Content(role = "model", parts = modelParts))
            }
            if (roundText.isNotEmpty()) lastText = roundText.toString()
            sink.emit(AgentEvent.ModelTurn(modelParts))

            // Las llamadas a función se ejecutan una vez cada una: si el modelo
            // repite la misma petición en varios eventos, no se duplica la acción.
            val calls = dedupe(modelParts.mapNotNull { it.functionCall })
            if (calls.isEmpty()) {
                sink.emit(AgentEvent.Done(lastText))
                return lastText
            }

            val responses = mutableListOf<Part>()
            for (call in calls) {
                responses.add(handleCall(call, settings, toolContext, confirmer, sink))
            }
            // El resultado de las herramientas vuelve como turno del usuario: así
            // es como Gemini espera las respuestas a `functionCall`.
            history.add(Content(role = "user", parts = responses))
        }

        // Se agotaron las rondas: el modelo sigue pidiendo herramientas y no
        // cierra. Mejor avisar que dejarlo en silencio.
        sink.emit(
            AgentEvent.Notice(
                "He hecho varias acciones seguidas y me he quedado sin pasos. " +
                    "¿Seguimos? Dime qué falta.",
            ),
        )
        sink.emit(AgentEvent.Done(lastText))
        return lastText
    }

    private suspend fun handleCall(
        call: FunctionCall,
        settings: AppSettings,
        toolContext: ToolContext,
        confirmer: Confirmer,
        sink: EventSink,
    ): Part {
        val tool = registry.byCallName(call.name)
            ?: return Part(
                functionResponse = FunctionResponse(
                    name = call.name,
                    id = call.id,
                    response = buildJsonObject {
                        put("resultado", "error")
                        put(
                            "resumen",
                            "No existe ninguna herramienta llamada «${call.name}».",
                        )
                    },
                ),
            )

        val args = call.args ?: JsonObject(emptyMap())
        val tier = tool.spec.tier
        val decision = Policy.decide(tier, settings.confirmEveryAction)

        if (decision == Decision.CONFIRM) {
            val allowed = confirmer.confirm(tool, args, tier)
            if (!allowed) {
                sink.emit(AgentEvent.ToolDenied(tool.spec.name))
                return Part(
                    functionResponse = FunctionResponse(
                        name = call.name,
                        id = call.id,
                        response = buildJsonObject {
                            put("resultado", "cancelado")
                            put("resumen", "El usuario rechazó la acción.")
                        },
                    ),
                )
            }
        }

        sink.emit(AgentEvent.ToolStarted(tool.spec.name, tier))

        val result = try {
            tool.execute(args, toolContext)
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e
        } catch (e: Exception) {
            // Una herramienta que revienta no puede tumbar la conversación: se
            // devuelve el fallo al modelo para que lo cuente y siga.
            ToolResult(
                ok = false,
                summary = "Falló ${tool.spec.name}: ${e.javaClass.simpleName} ${e.message.orEmpty()}".trim(),
            )
        }

        sink.emit(AgentEvent.ToolExecuted(tool.spec.name, result.summary, result.ok, tier))

        return Part(
            functionResponse = FunctionResponse(
                name = call.name,
                id = call.id,
                response = buildJsonObject {
                    put("resultado", if (result.ok) "ok" else "error")
                    put("resumen", result.summary)
                    // Los datos extra se copian al mismo nivel: el modelo los lee
                    // mejor así que anidados.
                    result.data.forEach { (key, value) -> put(key, value) }
                },
            ),
        )
    }

    /** Dos llamadas idénticas (mismo nombre y argumentos) son la misma acción. */
    private fun dedupe(calls: List<FunctionCall>): List<FunctionCall> {
        val seen = mutableSetOf<String>()
        return calls.filter { call ->
            val key = "${call.name}:${call.args?.toString().orEmpty()}"
            seen.add(key)
        }
    }

    /**
     * Recorta el contexto por delante.
     *
     * Solo se cortan turnos completos del usuario: si el primero de la lista fuese
     * el resultado de una herramienta, quedaría huérfano y la API daría 400 (una
     * `functionResponse` sin su `functionCall` correspondiente es inválida).
     */
    private fun pruneHistory(history: MutableList<Content>) {
        while (
            history.size > MAX_CONTENTS &&
            history.firstOrNull()?.parts?.none { it.functionResponse != null } == true
        ) {
            history.removeAt(0)
        }
    }

    companion object {
        /** Turnos máximos por mensaje del usuario (evita bucles infinitos). */
        const val MAX_TOOL_ROUNDS = 6

        /** Mensajes máximos de contexto enviados a la API (~40 mensajes). */
        const val MAX_CONTENTS = 40
    }
}

/** Utilidad para los tests y para el registro: representación corta de los args. */
fun JsonObject?.preview(): String = this?.let { json ->
    json.entries.joinToString(", ") { (key, value) ->
        val raw = (value as? JsonPrimitive)?.content ?: value.toString()
        "$key=$raw"
    }
} ?: ""
