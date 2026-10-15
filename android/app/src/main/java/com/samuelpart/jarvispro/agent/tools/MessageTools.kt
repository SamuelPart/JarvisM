package com.samuelpart.jarvispro.agent.tools

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.ContactsContract
import android.telephony.SmsManager
import com.samuelpart.jarvispro.agent.Args
import com.samuelpart.jarvispro.agent.Perms
import com.samuelpart.jarvispro.agent.RiskTier
import com.samuelpart.jarvispro.agent.Tool
import com.samuelpart.jarvispro.agent.ToolContext
import com.samuelpart.jarvispro.agent.ToolResult
import com.samuelpart.jarvispro.agent.ToolSpec
import com.samuelpart.jarvispro.data.AppSettings
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.add
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put
import java.text.Normalizer
import java.util.Locale

/** Contacto local (solo lo justo: nombre y número). */
data class PhoneContact(val name: String, val number: String)

/**
 * Busca un contacto por nombre aproximado.
 *
 * Nota de privacidad: la libreta NO se envía al modelo en ningún caso. Se
 * consulta en el teléfono, se resuelve el número y solo se manda el texto del
 * mensaje. El nombre que dijo el usuario tampoco sale de aquí.
 */
fun findContact(ctx: ToolContext, query: String): PhoneContact? {
    if (!Perms.hasContacts(ctx.context)) return null
    val needle = Normalizer.normalize(query.lowercase(Locale.ROOT), Normalizer.Form.NFD)
        .replace(Regex("\\p{Mn}+"), "")
        .replace(Regex("[^a-z0-9 ]"), " ")
        .trim()
    if (needle.isEmpty()) return null

    val projection = arrayOf(
        ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
        ContactsContract.CommonDataKinds.Phone.NUMBER,
    )
    val cursor = ctx.context.contentResolver.query(
        ContactsContract.CommonDataKinds.Phone.CONTENT_URI,
        projection,
        null,
        null,
        null,
    ) ?: return null

    var best: PhoneContact? = null
    cursor.use { c ->
        val nameIdx = c.getColumnIndex(projection[0])
        val numberIdx = c.getColumnIndex(projection[1])
        while (c.moveToNext()) {
            val name = c.getString(nameIdx) ?: continue
            val number = c.getString(numberIdx) ?: continue
            val normalizedName = Normalizer.normalize(name.lowercase(Locale.ROOT), Normalizer.Form.NFD)
                .replace(Regex("\\p{Mn}+"), "")
            if (normalizedName.contains(needle)) {
                // El primer acierto suele ser el más relevante; si es exacto, gana.
                if (normalizedName == needle) return PhoneContact(name, number)
                if (best == null) best = PhoneContact(name, number)
            }
        }
    }
    return best
}

/**
 * `send_sms`: enviar un mensaje de texto.
 *
 * Es la única herramienta T3: no se puede deshacer. Por eso:
 *   - solo existe si el usuario activó "Permitir enviar SMS" en Ajustes, y
 *   - la política la marca SIEMPRE como "pedir confirmación", incluso si el
 *     usuario activó el modo de confiar en todo.
 */
class SendSmsTool : Tool {

    override val spec = ToolSpec(
        name = "send_sms",
        description = "Envía un SMS a un contacto o a un número. " +
            "Necesita el permiso de SMS y el interruptor «Permitir enviar SMS» activado. " +
            "El usuario verá una confirmación antes de que salga el mensaje.",
        tier = RiskTier.T3,
        parameters = buildJsonObject {
            put("type", "object")
            put(
                "properties",
                buildJsonObject {
                    put("destinatario", buildJsonObject {
                        put("type", "string")
                        put("description", "Nombre del contacto o número de teléfono.")
                    })
                    put("mensaje", buildJsonObject {
                        put("type", "string")
                        put("description", "Texto del SMS.")
                    })
                },
            )
            put("required", buildJsonArray { add("destinatario"); add("mensaje") })
        },
    )

    override fun isEnabled(settings: AppSettings): Boolean = settings.allowSms

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        val destinatario = Args.str(args, "destinatario").trim()
        val mensaje = Args.str(args, "mensaje").trim()
        if (destinatario.isEmpty() || mensaje.isEmpty()) {
            return ToolResult(false, "Me falta el destinatario o el texto del mensaje.")
        }
        if (!Perms.hasSms(ctx.context)) {
            return ToolResult(
                false,
                "No tengo permiso para enviar SMS. Concédelo en Ajustes de la app → Permisos.",
                Args.response("permiso_faltante" to Args.text("SEND_SMS")),
            )
        }

        // ¿Número directo o nombre de contacto?
        val number = if (destinatario.count { it.isDigit() } >= 6) {
            destinatario.filter { it.isDigit() || it == '+' }
        } else {
            val contact = findContact(ctx, destinatario)
                ?: return ToolResult(
                    false,
                    "No encontré ningún contacto que se llame «$destinatario». " +
                        "Puedo enviarlo a un número si me lo das.",
                )
            contact.number
        }

        return try {
            val manager = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                ctx.context.getSystemService(SmsManager::class.java)
            } else {
                @Suppress("DEPRECATION")
                SmsManager.getDefault()
            }
            if (manager == null) return ToolResult(false, "Este dispositivo no tiene servicio de SMS.")

            val parts = manager.divideMessage(mensaje)
            manager.sendMultipartTextMessage(number, null, parts, null, null)
            ToolResult(
                ok = true,
                summary = "SMS enviado a $number.",
                data = Args.response("numero" to Args.text(number), "caracteres" to Args.number(mensaje.length)),
            )
        } catch (e: Exception) {
            ToolResult(false, "No se pudo enviar el SMS (${e.javaClass.simpleName}).")
        }
    }
}

/**
 * `compose_sms`: alternativa sin permisos.
 *
 * Abre la app de mensajes con el texto ya escrito y el destinatario puesto, y el
 * usuario pulsa "enviar". No necesita SEND_SMS ni leer contactos, así que está
 * disponible siempre y es el camino recomendado si no quieres dar el permiso.
 */
class ComposeSmsTool : Tool {

    override val spec = ToolSpec(
        name = "compose_sms",
        description = "Abre la app de mensajes con un SMS preparado (texto y destinatario). " +
            "El usuario solo tiene que pulsar enviar. No pide ningún permiso.",
        tier = RiskTier.T2,
        parameters = buildJsonObject {
            put("type", "object")
            put(
                "properties",
                buildJsonObject {
                    put("numero", buildJsonObject {
                        put("type", "string")
                        put("description", "Número de teléfono del destinatario.")
                    })
                    put("mensaje", buildJsonObject {
                        put("type", "string")
                        put("description", "Texto del mensaje.")
                    })
                },
            )
            put("required", buildJsonArray { add("numero"); add("mensaje") })
        },
    )

    override suspend fun execute(args: JsonObject, ctx: ToolContext): ToolResult {
        val number = Args.str(args, "numero").filter { it.isDigit() || it == '+' }
        val message = Args.str(args, "mensaje")
        if (number.length < 6) return ToolResult(false, "Necesito un número de teléfono válido.")

        val intent = Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:$number"))
            .putExtra("sms_body", message)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        return try {
            ctx.context.startActivity(intent)
            ToolResult(true, "Mensaje preparado para el $number; pulsa enviar en la app de mensajes.")
        } catch (e: Exception) {
            ToolResult(false, "No pude abrir la app de mensajes.")
        }
    }
}
