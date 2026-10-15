package com.samuelpart.jarvispro.agent.tools

import android.content.Context
import android.content.Intent
import android.hardware.camera2.CameraAccessException
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.media.AudioManager
import android.net.Uri
import android.provider.Settings
import com.samuelpart.jarvispro.agent.Args
import com.samuelpart.jarvispro.agent.Perms
import com.samuelpart.jarvispro.agent.RiskTier
import com.samuelpart.jarvispro.agent.Tool
import com.samuelpart.jarvispro.agent.ToolContext
import com.samuelpart.jarvispro.agent.ToolResult
import com.samuelpart.jarvispro.agent.ToolSpec
import com.samuelpart.jarvispro.agent.Policy
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import kotlin.math.roundToInt

/** Estado de la linterna, a nivel de proceso: Android no da un "¿está encendida?". */
object FlashlightState {
    @Volatile
    var isOn: Boolean = false
}

/** `set_volume`: subir, bajar, fijar, silenciar o consultar el volumen. */
class SetVolumeTool : Tool {

    override val spec = ToolSpec(
        name = "set_volume",
        description = "Cambia o consulta el volumen del teléfono. " +
            "Usa «accion» para indicar qué hacer y «porcentaje» (0-100) cuando aplique. " +
            "Si el usuario dice «sube el volumen» sin más, usa accion=subir sin porcentaje.",
        tier = RiskTier.T1,
        parameters = buildJsonObject {
            put("type", "object")
            put(
                "properties",
                buildJsonObject {
                    put(
                        "accion",
                        buildJsonObject {
                            put("type", "string")
                            put(
                                "description",
                                "subir | bajar | fijar | silenciar | consultar",
                            )
                            put(
                                "enum",
                                buildJsonArray {
                                    add("subir"); add("bajar"); add("fijar")
                                    add("silenciar"); add("consultar")
                                },
                            )
                        },
                    )
                    put(
                        "porcentaje",
                        buildJsonObject {
                            put("type", "integer")
                            put("description", "Nivel objetivo o cantidad a subir/bajar, de 0 a 100.")
                        },
                    )
                    put(
                        "stream",
                        buildJsonObject {
                            put("type", "string")
                            put("description", "Tipo de volumen: media (defecto), alarma, timbre, notificacion o sistema.")
                            put(
                                "enum",
                                buildJsonArray {
                                    add("media"); add("alarma"); add("timbre")
                                    add("notificacion"); add("sistema")
                                },
                            )
                        },
                    )
                },
            )
            put("required", buildJsonArray { add("accion") })
        },
    )

    private fun streamFor(name: String): Pair<Int, String> = when (name.lowercase()) {
        "alarma", "alarm" -> AudioManager.STREAM_ALARM to "alarma"
        "timbre", "llamada", "ring", "tono" -> AudioManager.STREAM_RING to "timbre"
        "notificacion", "notificación" -> AudioManager.STREAM_NOTIFICATION to "notificaciones"
        "sistema", "system" -> AudioManager.STREAM_SYSTEM to "sistema"
        else -> AudioManager.STREAM_MUSIC to "multimedia"
    }

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        val am = ctx.context.getSystemService(Context.AUDIO_SERVICE) as? AudioManager
            ?: return ToolResult(false, "No pude acceder al control de volumen.")
        val (stream, streamName) = streamFor(Args.str(args, "stream", "media"))
        val max = am.getStreamMaxVolume(stream).coerceAtLeast(1)
        val current = am.getStreamVolume(stream)
        val currentPct = (current * 100f / max).roundToInt()

        return try {
            when (Args.str(args, "accion", "consultar").lowercase()) {
                "consultar" -> ToolResult(
                    true,
                    "El volumen de $streamName está al $currentPct %.",
                    Args.response("porcentaje" to Args.number(currentPct)),
                )

                "silenciar" -> {
                    am.setStreamVolume(stream, 0, 0)
                    ToolResult(true, "Volumen de $streamName silenciado.", Args.response("porcentaje" to Args.number(0)))
                }

                "fijar" -> {
                    val pct = Args.int(args, "porcentaje", currentPct).coerceIn(0, 100)
                    am.setStreamVolume(stream, (max * pct / 100f).roundToInt().coerceIn(0, max), 0)
                    ToolResult(
                        true,
                        "Volumen de $streamName al $pct %.",
                        Args.response("porcentaje" to Args.number(pct)),
                    )
                }

                "subir", "bajar" -> {
                    val step = Args.intOrNull(args, "porcentaje") ?: DEFAULT_STEP_PCT
                    val delta = if (Args.str(args, "accion").lowercase() == "subir") step else -step
                    val target = (currentPct + delta).coerceIn(0, 100)
                    am.setStreamVolume(stream, (max * target / 100f).roundToInt().coerceIn(0, max), 0)
                    ToolResult(
                        true,
                        "Volumen de $streamName: $currentPct % → $target %.",
                        Args.response("porcentaje" to Args.number(target)),
                    )
                }

                else -> ToolResult(false, "No entendí qué hacer con el volumen (accion=«${Args.str(args, "accion")}»).")
            }
        } catch (e: SecurityException) {
            ToolResult(false, "Android bloqueó el cambio de volumen (no molestar activo).")
        }
    }

    private companion object {
        const val DEFAULT_STEP_PCT = 10
    }
}

/** `flashlight`: enciende o apaga la linterna. */
class FlashlightTool : Tool {

    override val spec = ToolSpec(
        name = "flashlight",
        description = "Enciende o apaga la linterna (el flash de la cámara).",
        tier = RiskTier.T1,
        parameters = buildJsonObject {
            put("type", "object")
            put(
                "properties",
                buildJsonObject {
                    put(
                        "encender",
                        buildJsonObject {
                            put("type", "boolean")
                            put("description", "true para encender, false para apagar.")
                        },
                    )
                },
            )
            put("required", buildJsonArray { add("encender") })
        },
    )

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        val manager = ctx.context.getSystemService(Context.CAMERA_SERVICE) as? CameraManager
            ?: return ToolResult(false, "Este teléfono no expone el servicio de cámara.")

        val cameraId = try {
            manager.cameraIdList.firstOrNull { id ->
                val characteristics = manager.getCameraCharacteristics(id)
                characteristics.get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true &&
                    characteristics.get(CameraCharacteristics.LENS_FACING) ==
                    CameraCharacteristics.LENS_FACING_BACK
            } ?: manager.cameraIdList.firstOrNull { id ->
                manager.getCameraCharacteristics(id)
                    .get(CameraCharacteristics.FLASH_INFO_AVAILABLE) == true
            }
        } catch (e: CameraAccessException) {
            null
        }

        if (cameraId == null) return ToolResult(false, "Este teléfono no tiene linterna.")

        val want = Args.boolOrNull(args, "encender")
            ?: return ToolResult(false, "No me quedó claro si quieres encenderla o apagarla.")

        return try {
            manager.setTorchMode(cameraId, want)
            FlashlightState.isOn = want
            ToolResult(
                true,
                if (want) "Linterna encendida." else "Linterna apagada.",
                Args.response("encendida" to Args.flag(want)),
            )
        } catch (e: Exception) {
            ToolResult(false, "No pude cambiar la linterna (${e.javaClass.simpleName}): puede estar en uso por la cámara.")
        }
    }
}

/** `set_brightness`: brillo de la pantalla. Necesita permiso especial de escritura. */
class SetBrightnessTool : Tool {

    override val spec = ToolSpec(
        name = "set_brightness",
        description = "Ajusta el brillo de la pantalla entre 0 y 100 %. " +
            "Requiere que el usuario haya concedido el permiso «modificar ajustes del sistema» " +
            "(la app lo pide al abrir Ajustes → Permisos).",
        tier = RiskTier.T1,
        parameters = buildJsonObject {
            put("type", "object")
            put(
                "properties",
                buildJsonObject {
                    put(
                        "porcentaje",
                        buildJsonObject {
                            put("type", "integer")
                            put("description", "Brillo objetivo de 0 a 100.")
                        },
                    )
                },
            )
            put("required", buildJsonArray { add("porcentaje") })
        },
    )

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        val pct = Args.intOrNull(args, "porcentaje")
            ?: return ToolResult(false, "No me dijiste qué brillo poner.")
        if (!Perms.canWriteSettings(ctx.context)) {
            return ToolResult(
                false,
                "Me falta el permiso «modificar ajustes del sistema». " +
                    "Actívalo en Ajustes de la app → Permisos → Brillo.",
                Args.response("permiso_faltante" to Args.text("WRITE_SETTINGS")),
            )
        }
        val value = (255 * pct.coerceIn(0, 100) / 100f).roundToInt()
        return try {
            Settings.System.putInt(
                ctx.context.contentResolver,
                Settings.System.SCREEN_BRIGHTNESS,
                value.coerceIn(1, 255),
            )
            ToolResult(true, "Brillo al $pct %.", Args.response("porcentaje" to Args.number(pct)))
        } catch (e: Exception) {
            ToolResult(false, "No pude cambiar el brillo (${e.javaClass.simpleName}).")
        }
    }
}

/** `open_settings`: abre una pantalla concreta de los ajustes de Android. */
class OpenSettingsTool : Tool {

    override val spec = ToolSpec(
        name = "open_settings",
        description = "Abre una pantalla de ajustes del sistema. Si no sabes cuál, usa «general».",
        tier = RiskTier.T2,
        parameters = buildJsonObject {
            put("type", "object")
            put(
                "properties",
                buildJsonObject {
                    put(
                        "pantalla",
                        buildJsonObject {
                            put("type", "string")
                            put("description", "wifi | bluetooth | sonido | pantalla | bateria | apps | ubicacion | general")
                            put(
                                "enum",
                                buildJsonArray {
                                    add("wifi"); add("bluetooth"); add("sonido"); add("pantalla")
                                    add("bateria"); add("apps"); add("ubicacion"); add("general")
                                },
                            )
                        },
                    )
                },
            )
            put("required", buildJsonArray { add("pantalla") })
        },
    )

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        val action = when (Args.str(args, "pantalla", "general").lowercase()) {
            "wifi" -> Settings.ACTION_WIFI_SETTINGS
            "bluetooth" -> Settings.ACTION_BLUETOOTH_SETTINGS
            "sonido", "volumen" -> Settings.ACTION_SOUND_SETTINGS
            "pantalla", "brillo" -> Settings.ACTION_DISPLAY_SETTINGS
            "bateria", "batería" -> Settings.ACTION_BATTERY_SAVER_SETTINGS
            "apps", "aplicaciones" -> Settings.ACTION_APPLICATION_SETTINGS
            "ubicacion", "ubicación", "gps" -> Settings.ACTION_LOCATION_SOURCE_SETTINGS
            else -> Settings.ACTION_SETTINGS
        }
        return try {
            ctx.context.startActivity(Intent(action).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            ToolResult(true, "Abriendo ajustes de ${Args.str(args, "pantalla", "general")}.")
        } catch (e: Exception) {
            ToolResult(false, "Este teléfono no tiene esa pantalla de ajustes.")
        }
    }
}

/** `open_web`: abre una dirección en el navegador. */
class OpenWebTool : Tool {

    override val spec = ToolSpec(
        name = "open_web",
        description = "Abre una página web en el navegador. Acepta «google.com» o " +
            "«https://www.google.com». También sirve para búsquedas: " +
            "«https://www.google.com/search?q=…».",
        tier = RiskTier.T2,
        parameters = buildJsonObject {
            put("type", "object")
            put(
                "properties",
                buildJsonObject {
                    put(
                        "url",
                        buildJsonObject {
                            put("type", "string")
                            put("description", "Dirección web. Si no lleva https://, se añade.")
                        },
                    )
                },
            )
            put("required", buildJsonArray { add("url") })
        },
    )

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        var url = Args.str(args, "url").trim()
        if (url.isEmpty()) return ToolResult(false, "No me dijiste qué página abrir.")
        if (!url.contains("://")) url = "https://$url"

        // Lista blanca de esquemas: el modelo (o un mensaje ajeno) no puede colar
        // un `javascript:` ni un `file://` que saque al usuario de la app.
        if (!Policy.isSafeUrl(url)) {
            return ToolResult(false, "Por seguridad solo abro direcciones http o https.")
        }
        return try {
            ctx.context.startActivity(
                Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
            ToolResult(true, "Abriendo $url.", Args.response("url" to Args.text(url)))
        } catch (e: Exception) {
            ToolResult(false, "Ningún navegador pudo abrir esa dirección.")
        }
    }
}

/** `make_call`: abre el marcador con el número puesto (no llama solo). */
class MakeCallTool : Tool {

    override val spec = ToolSpec(
        name = "make_call",
        description = "Abre el marcador del teléfono con un número listo para llamar. " +
            "NO llama directamente: deja que el usuario pulse el botón verde.",
        tier = RiskTier.T2,
        parameters = buildJsonObject {
            put("type", "object")
            put(
                "properties",
                buildJsonObject {
                    put(
                        "numero",
                        buildJsonObject {
                            put("type", "string")
                            put("description", "Número de teléfono, puede llevar prefijo +51.")
                        },
                    )
                },
            )
            put("required", buildJsonArray { add("numero") })
        },
    )

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        val number = Args.str(args, "numero").filter { it.isDigit() || it == '+' }
        if (number.length < 3) return ToolResult(false, "Ese número no parece válido.")
        return try {
            ctx.context.startActivity(
                Intent(Intent.ACTION_DIAL, Uri.parse("tel:$number"))
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
            )
            ToolResult(true, "Marcador abierto con el $number.", Args.response("numero" to Args.text(number)))
        } catch (e: Exception) {
            ToolResult(false, "No pude abrir el marcador.")
        }
    }
}
