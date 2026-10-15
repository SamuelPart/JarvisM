package com.samuelpart.jarvispro.ui

import com.samuelpart.jarvispro.agent.RiskTier

/**
 * Lo que se pinta en la conversación.
 *
 * Ojo: esto NO es el contexto que se manda a la API (ese vive en el ViewModel
 * como `Content` de Gemini, con sus partes y firmas). Aquí solo hay texto para
 * personas, más los datos necesarios para pintar las etiquetas de las acciones.
 */
data class ChatItem(
    val id: Long,
    val role: Role,
    val text: String,
    val toolName: String? = null,
    val tier: RiskTier? = null,
    /** true mientras el texto se está recibiendo (dibuja el cursor parpadeante). */
    val streaming: Boolean = false,
    val ok: Boolean = true,
) {
    enum class Role { USER, JARVIS, TOOL, NOTICE, ERROR }
}

/** Acción pendiente de permiso del usuario. */
data class PendingConfirmation(
    val toolName: String,
    val description: String,
    val argsPreview: String,
    val tier: RiskTier,
)

/** Nombre legible de una herramienta, para las etiquetas de la interfaz. */
fun humanToolName(name: String): String = when (name) {
    "list_apps" -> "ver apps instaladas"
    "open_app" -> "abrir app"
    "set_volume" -> "volumen"
    "flashlight" -> "linterna"
    "set_brightness" -> "brillo"
    "open_settings" -> "ajustes de Android"
    "open_web" -> "abrir web"
    "make_call" -> "llamar"
    "set_alarm" -> "poner alarma"
    "set_reminder" -> "crear recordatorio"
    "send_sms" -> "enviar SMS"
    "compose_sms" -> "preparar SMS"
    "battery_status" -> "batería"
    "device_info" -> "info del teléfono"
    else -> name
}
