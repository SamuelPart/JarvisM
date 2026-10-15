package com.samuelpart.jarvispro.agent.tools

import android.app.AlarmManager
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.BatteryManager
import android.os.Build
import com.samuelpart.jarvispro.agent.Args
import com.samuelpart.jarvispro.agent.RiskTier
import com.samuelpart.jarvispro.agent.Tool
import com.samuelpart.jarvispro.agent.ToolContext
import com.samuelpart.jarvispro.agent.ToolResult
import com.samuelpart.jarvispro.agent.ToolSpec
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** `battery_status`: nivel de batería y si está cargando. */
class BatteryTool : Tool {

    override val spec = ToolSpec(
        name = "battery_status",
        description = "Dice el nivel de batería, si está cargando y la temperatura aproximada.",
        tier = RiskTier.T0,
        parameters = buildJsonObject { put("type", "object") },
    )

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        val intent = ctx.context.registerReceiver(null, IntentFilter(Intent.ACTION_BATTERY_CHANGED))
            ?: return ToolResult(false, "No pude leer el estado de la batería.")

        val level = intent.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = intent.getIntExtra(BatteryManager.EXTRA_SCALE, 100)
        val pct = if (level >= 0 && scale > 0) level * 100 / scale else -1
        val status = intent.getIntExtra(BatteryManager.EXTRA_STATUS, -1)
        val charging = status == BatteryManager.BATTERY_STATUS_CHARGING ||
            status == BatteryManager.BATTERY_STATUS_FULL
        val tempC = intent.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, 0) / 10.0

        val text = buildString {
            append("Batería al $pct %")
            append(if (charging) " (cargando)" else "")
            if (tempC > 0) append(", ${"%.1f".format(tempC)} °C")
        }
        return ToolResult(
            ok = true,
            summary = text,
            data = buildJsonObject {
                put("porcentaje", pct)
                put("cargando", charging)
                put("temperatura_c", tempC)
            },
        )
    }
}

/** `device_info`: datos del teléfono y del entorno de la app. */
class DeviceInfoTool : Tool {

    override val spec = ToolSpec(
        name = "device_info",
        description = "Información del dispositivo: modelo, versión de Android, " +
            "idioma y hora actual. Útil para responder cosas como «¿qué hora es?».",
        tier = RiskTier.T0,
        parameters = buildJsonObject { put("type", "object") },
    )

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        val now = Date()
        val time = SimpleDateFormat("HH:mm", Locale.getDefault()).format(now)
        val date = SimpleDateFormat("EEEE d 'de' MMMM 'de' yyyy", Locale("es")).format(now)
        val tz = java.util.TimeZone.getDefault().id

        val alarmManager = ctx.context.getSystemService(Context.ALARM_SERVICE) as? AlarmManager
        val nextAlarm = alarmManager?.nextAlarmClock?.triggerTime

        val summary = buildString {
            append("Son las $time del $date. ")
            append("Dispositivo ${Build.MANUFACTURER} ${Build.MODEL}, Android ${Build.VERSION.RELEASE}. ")
            append("Zona horaria $tz.")
            if (nextAlarm != null) {
                append(" Próxima alarma: ")
                append(SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(nextAlarm)))
                append(".")
            }
        }
        return ToolResult(
            ok = true,
            summary = summary,
            data = buildJsonObject {
                put("hora", time)
                put("fecha", date)
                put("modelo", "${Build.MANUFACTURER} ${Build.MODEL}")
                put("android", Build.VERSION.RELEASE)
                put("zona_horaria", tz)
            },
        )
    }
}

/** `set_alarm`: crea una alarma en el reloj del sistema. */
class SetAlarmTool : Tool {

    override val spec = ToolSpec(
        name = "set_alarm",
        description = "Programa una alarma en la app de reloj. " +
            "Usa «hora» en formato 24 h (por ejemplo «07:30») o «en_minutos» " +
            "para dentro de X minutos.",
        tier = RiskTier.T2,
        parameters = buildJsonObject {
            put("type", "object")
            put(
                "properties",
                buildJsonObject {
                    put("hora", buildJsonObject {
                        put("type", "string")
                        put("description", "Hora en formato HH:MM (24 h), por ejemplo «06:45».")
                    })
                    put("en_minutos", buildJsonObject {
                        put("type", "integer")
                        put("description", "Alternativa a «hora»: dentro de N minutos.")
                    })
                    put("etiqueta", buildJsonObject {
                        put("type", "string")
                        put("description", "Texto de la alarma, por ejemplo «gimnasio».")
                    })
                },
            )
        },
    )

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        val minutesFromNow = Args.intOrNull(args, "en_minutos")
        val (hour, minute) = when {
            minutesFromNow != null -> {
                val target = java.util.Calendar.getInstance().apply { add(java.util.Calendar.MINUTE, minutesFromNow) }
                target.get(java.util.Calendar.HOUR_OF_DAY) to target.get(java.util.Calendar.MINUTE)
            }

            else -> {
                val raw = Args.str(args, "hora").trim()
                val parts = raw.split(":", "h", "H").mapNotNull { it.trim().toIntOrNull() }
                if (parts.size < 2) {
                    return ToolResult(
                        false,
                        "Necesito una hora del tipo «07:30» o un número de minutos.",
                    )
                }
                (parts[0] % 24) to (parts[1] % 60)
            }
        }

        val intent = Intent(android.provider.AlarmClock.ACTION_SET_ALARM)
            .putExtra(android.provider.AlarmClock.EXTRA_HOUR, hour)
            .putExtra(android.provider.AlarmClock.EXTRA_MINUTES, minute)
            .putExtra(android.provider.AlarmClock.EXTRA_SKIP_UI, false)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

        Args.str(args, "etiqueta").takeIf { it.isNotBlank() }?.let {
            intent.putExtra(android.provider.AlarmClock.EXTRA_MESSAGE, it)
        }

        return try {
            ctx.context.startActivity(intent)
            val label = "; pasa por el reloj para confirmarla"
            ToolResult(
                true,
                "Alarma a las %02d:%02d%s".format(hour, minute, label),
                Args.response("hora" to Args.text("%02d:%02d".format(hour, minute))),
            )
        } catch (e: Exception) {
            ToolResult(false, "Este teléfono no tiene una app de reloj que acepte alarmas.")
        }
    }
}
