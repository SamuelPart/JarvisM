package com.samuelpart.jarvispro.agent.tools

import android.content.Intent
import android.provider.CalendarContract
import com.samuelpart.jarvispro.agent.Args
import com.samuelpart.jarvispro.agent.RiskTier
import com.samuelpart.jarvispro.agent.Tool
import com.samuelpart.jarvispro.agent.ToolContext
import com.samuelpart.jarvispro.agent.ToolResult
import com.samuelpart.jarvispro.agent.ToolSpec
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.util.Calendar

/**
 * `set_reminder`: crea un recordatorio en el calendario del sistema.
 *
 * Se usa `ACTION_INSERT` con la hora ya rellenada: Android abre la pantalla de
 * nuevo evento con los datos puestos y es el usuario quien guarda. Es intencional
 * — un recordatorio que aparece por sorpresa en su calendario sería peor que no
 * tenerlo, y así no hace falta pedir permisos de calendario para escribir.
 */
class SetReminderTool : Tool {

    override val spec = ToolSpec(
        name = "set_reminder",
        description = "Abre el calendario con un recordatorio preparado (título y hora). " +
            "Usa «en_minutos» o «hora» (HH:MM) para la hora del aviso.",
        tier = RiskTier.T2,
        parameters = buildJsonObject {
            put("type", "object")
            put(
                "properties",
                buildJsonObject {
                    put("titulo", buildJsonObject {
                        put("type", "string")
                        put("description", "De qué hay que acordarse, por ejemplo «llamar al banco».")
                    })
                    put("hora", buildJsonObject {
                        put("type", "string")
                        put("description", "Hora del aviso en formato HH:MM (24 h).")
                    })
                    put("en_minutos", buildJsonObject {
                        put("type", "integer")
                        put("description", "Alternativa a «hora»: dentro de N minutos.")
                    })
                },
            )
            put("required", buildJsonArray { add("titulo") })
        },
    )

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        val title = Args.str(args, "titulo").trim()
        if (title.isEmpty()) return ToolResult(false, "No me dijiste de qué hay que acordarse.")

        val calendar = Calendar.getInstance().apply { set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0) }
        when {
            Args.intOrNull(args, "en_minutos") != null ->
                calendar.add(Calendar.MINUTE, Args.int(args, "en_minutos"))

            Args.str(args, "hora").isNotBlank() -> {
                val parts = Args.str(args, "hora").split(":", "h", "H").mapNotNull { it.trim().toIntOrNull() }
                if (parts.size < 2) return ToolResult(false, "La hora debe ser del tipo «15:30».")
                calendar.set(Calendar.HOUR_OF_DAY, parts[0] % 24)
                calendar.set(Calendar.MINUTE, parts[1] % 60)
                if (calendar.timeInMillis < System.currentTimeMillis()) {
                    calendar.add(Calendar.DAY_OF_YEAR, 1) // Ya pasó hoy: mañana.
                }
            }
        }

        val intent = Intent(Intent.ACTION_INSERT)
            .setData(CalendarContract.Events.CONTENT_URI)
            .putExtra(CalendarContract.Events.TITLE, title)
            .putExtra(CalendarContract.EXTRA_EVENT_BEGIN_TIME, calendar.timeInMillis)
            .putExtra(CalendarContract.EXTRA_EVENT_END_TIME, calendar.timeInMillis + 30 * 60 * 1000)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

        return try {
            ctx.context.startActivity(intent)
            val stamp = "%02d:%02d".format(calendar.get(Calendar.HOUR_OF_DAY), calendar.get(Calendar.MINUTE))
            ToolResult(
                true,
                "Recordatorio «$title» preparado para las $stamp; guárdalo en el calendario.",
                Args.response("titulo" to Args.text(title), "hora" to Args.text(stamp)),
            )
        } catch (e: Exception) {
            ToolResult(false, "Este teléfono no tiene una app de calendario compatible.")
        }
    }
}
