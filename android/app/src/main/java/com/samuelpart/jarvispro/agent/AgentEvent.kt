package com.samuelpart.jarvispro.agent

import com.samuelpart.jarvispro.gemini.Part

/**
 * Todo lo que puede pasar durante un turno de conversación.
 *
 * El agente no conoce la interfaz ni Android: emite eventos y quien los reciba
 * decide qué hacer. Eso es lo que permite probar el bucle completo sin teléfono.
 */
sealed interface AgentEvent {

    /** Trozo de texto del modelo, según va llegando (streaming). */
    data class Text(val chunk: String) : AgentEvent

    /** El modelo cerró su turno: se guardan sus parts (con firmas) para el contexto. */
    data class ModelTurn(val parts: List<Part>) : AgentEvent

    /** Se va a ejecutar (o a pedir permiso para) una herramienta. */
    data class ToolStarted(val name: String, val tier: RiskTier) : AgentEvent

    /** La herramienta terminó. */
    data class ToolExecuted(
        val name: String,
        val summary: String,
        val ok: Boolean,
        val tier: RiskTier,
    ) : AgentEvent

    /** El usuario dijo que no a una acción. */
    data class ToolDenied(val name: String) : AgentEvent

    /** Aviso neutro para el usuario ("no puedo hacer eso", "me falta el permiso X"). */
    data class Notice(val message: String) : AgentEvent

    /** El turno terminó. `text` es la respuesta final del asistente (puede ir vacía). */
    data class Done(val text: String) : AgentEvent
}
