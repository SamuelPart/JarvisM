package com.samuelpart.jarvispro.agent.tools

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
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
import java.text.Normalizer
import java.util.Locale

/**
 * Herramientas para abrir aplicaciones del teléfono.
 *
 * El problema real: el usuario dice "abre wasap" y el modelo propone
 * `app="wasap"`. Ninguna app se llama así. Por eso aquí no se compara texto
 * exacto: se normaliza (minúsculas, sin acentos, sin símbolos) y se busca por
 * coincidencia parcial contra las etiquetas reales de las apps instaladas.
 */
private fun normalize(value: String): String {
    val lower = value.lowercase(Locale.ROOT).trim()
    val noAccents = Normalizer.normalize(lower, Normalizer.Form.NFD)
        .replace(Regex("\\p{Mn}+"), "")
    return noAccents.replace(Regex("[^a-z0-9]+"), " ").trim()
}

/** Alias habituales en español -> nombres reales de paquete. */
private val PACKAGE_ALIASES = mapOf(
    "whatsapp" to "com.whatsapp",
    "wasap" to "com.whatsapp",
    "whatsap" to "com.whatsapp",
    "wsp" to "com.whatsapp",
    "whatsapp business" to "com.whatsapp.w4b",
    "telegram" to "org.telegram.messenger",
    "youtube" to "com.google.android.youtube",
    "camera" to "com.android.camera",
    "camara" to "com.android.camera",
    "calculadora" to "com.android.calculator",
    "reloj" to "com.android.deskclock",
    "alarma" to "com.android.deskclock",
    "calendario" to "com.android.calendar",
    "contactos" to "com.android.contacts",
    "telefono" to "com.android.dialer",
    "llamadas" to "com.android.dialer",
    "mensajes" to "com.android.messaging",
    "sms" to "com.android.messaging",
    "spotify" to "com.spotify.music",
    "instagram" to "com.instagram.android",
    "facebook" to "com.facebook.katana",
    "tiktok" to "com.zhiliaoapp.musically",
    "maps" to "com.google.android.apps.maps",
    "mapas" to "com.google.android.apps.maps",
    "gmail" to "com.google.android.gm",
    "correo" to "com.google.android.gm",
    "chrome" to "com.android.chrome",
    "galeria" to "com.google.android.apps.photos",
    "fotos" to "com.google.android.apps.photos",
    "ajustes" to "com.android.settings",
    "configuracion" to "com.android.settings",
    "play store" to "com.android.vending",
    "tienda" to "com.android.vending",
    "netflix" to "com.netflix.mediaclient",
)

/** Una app instalada, ya reducida a lo que necesitamos. */
data class InstalledApp(val label: String, val packageName: String) {
    val normalizedLabel: String get() = normalize(label)
}

/** Lista las apps con lanzador. No necesita permiso: se ven por el <queries> del manifiesto. */
fun installedApps(context: Context): List<InstalledApp> {
    val pm = context.packageManager
    val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
    val infos = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
        pm.queryIntentActivities(intent, PackageManager.ResolveInfoFlags.of(0L))
    } else {
        @Suppress("DEPRECATION")
        pm.queryIntentActivities(intent, 0)
    }
    return infos
        .mapNotNull { info ->
            val pkg = info.activityInfo?.packageName ?: return@mapNotNull null
            val label = runCatching { info.loadLabel(pm).toString() }.getOrDefault(pkg)
            InstalledApp(label, pkg)
        }
        .distinctBy { it.packageName }
        .sortedBy { it.label.lowercase(Locale.ROOT) }
}

/**
 * Busca la app que mejor encaje con lo que dijo el usuario.
 * Devuelve también las alternativas, para poder decir "no encontré X, ¿querías Y?"
 */
fun findApp(context: Context, query: String): Pair<InstalledApp?, List<InstalledApp>> {
    val apps = installedApps(context)
    val needle = normalize(query)
    if (needle.isEmpty()) return null to emptyList()

    // 1) Alias conocido en español.
    PACKAGE_ALIASES[needle]?.let { pkg ->
        apps.firstOrNull { it.packageName == pkg }?.let { return it to emptyList() }
    }

    // 2) Coincidencia exacta con la etiqueta.
    apps.firstOrNull { it.normalizedLabel == needle }?.let { return it to emptyList() }

    // 3) Coincidencia por paquete exacto ("com.whatsapp").
    apps.firstOrNull { it.packageName.equals(query.trim(), ignoreCase = true) }
        ?.let { return it to emptyList() }

    // 4) La etiqueta contiene lo dicho o al revés ("wasap" ⊂ "whatsapp").
    val partial = apps.filter {
        it.normalizedLabel.contains(needle) || needle.contains(it.normalizedLabel)
    }
    if (partial.isNotEmpty()) return partial.first() to partial.drop(1).take(4)

    // 5) Sin coincidencia directa: se sugieren las más parecidas por prefijo.
    val prefix = apps.filter { it.normalizedLabel.startsWith(needle.take(3)) && needle.length >= 3 }
    return null to prefix.take(4)
}

/** `list_apps`: el modelo lo usa para saber qué hay instalado antes de proponer. */
class ListAppsTool : Tool {
    override val spec = ToolSpec(
        name = "list_apps",
        description = "Devuelve la lista de aplicaciones instaladas con lanzador. " +
            "Úsala cuando no sepas si una app está instalada o para desambiguar un nombre.",
        tier = RiskTier.T0,
        // Gemini exige que `parameters` sea un objeto, aunque no tenga campos.
        parameters = buildJsonObject {
            put("type", "object")
            put(
                "properties",
                buildJsonObject {
                    put(
                        "contains",
                        buildJsonObject {
                            put("type", "string")
                            put("description", "Texto a buscar. Si se omite, devuelve todas.")
                        },
                    )
                },
            )
        },
    )

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        val contains = Args.str(args, "contains")
        val apps = installedApps(ctx.context)
        val filtered = if (contains.isBlank()) apps
        else apps.filter { it.normalizedLabel.contains(normalize(contains)) }

        if (filtered.isEmpty()) {
            return ToolResult(false, "No hay ninguna app que coincida con «$contains».")
        }
        val names = filtered.take(60).map { it.label }
        return ToolResult(
            ok = true,
            summary = "${filtered.size} app(s): " + names.joinToString(", "),
            data = buildJsonObject {
                put("count", filtered.size)
                put("apps", buildJsonArray { names.forEach { add(it) } })
            },
        )
    }
}

/** `open_app`: abre una aplicación por nombre. */
class OpenAppTool : Tool {
    override val spec = ToolSpec(
        name = "open_app",
        description = "Abre una aplicación instalada en el teléfono. " +
            "Acepta el nombre común en español («whatsapp», «ajustes») o el paquete exacto. " +
            "Si no existe, devuelve las alternativas disponibles.",
        tier = RiskTier.T2,
        parameters = buildJsonObject {
            put("type", "object")
            put(
                "properties",
                buildJsonObject {
                    put(
                        "app",
                        buildJsonObject {
                            put("type", "string")
                            put("description", "Nombre de la app, por ejemplo «whatsapp» o «ajustes».")
                        },
                    )
                },
            )
            put("required", buildJsonArray { add("app") })
        },
    )

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        val query = Args.str(args, "app")
        if (query.isBlank()) return ToolResult(false, "No me dijiste qué aplicación abrir.")

        val (app, alternatives) = findApp(ctx.context, query)
        if (app == null) {
            val hint = if (alternatives.isEmpty()) {
                "No encontré ninguna app parecida a «$query». Usa list_apps para ver qué hay instalado."
            } else {
                "No encontré «$query». ¿Quizá querías alguna de estas? " +
                    alternatives.joinToString(", ") { it.label }
            }
            return ToolResult(false, hint, Args.response("alternativas" to Args.text(
                alternatives.joinToString(", ") { it.label },
            )))
        }

        val intent = ctx.context.packageManager.getLaunchIntentForPackage(app.packageName)
            ?: return ToolResult(
                false,
                "«${app.label}» está instalada pero no se puede abrir desde aquí.",
            )
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            ctx.context.startActivity(intent)
            ToolResult(
                ok = true,
                summary = "Abriendo ${app.label}.",
                data = Args.response("app" to Args.text(app.label), "paquete" to Args.text(app.packageName)),
            )
        } catch (e: Exception) {
            ToolResult(false, "No pude abrir ${app.label} (${e.javaClass.simpleName}).")
        }
    }
}
