package com.samuelpart.jarvispro.agent

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat

/** Comprobación de permisos en un solo sitio, para no repetir el `if` feliz. */
object Perms {

    fun has(context: Context, permission: String): Boolean =
        ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

    fun hasMic(context: Context): Boolean = has(context, Manifest.permission.RECORD_AUDIO)

    fun hasSms(context: Context): Boolean = has(context, Manifest.permission.SEND_SMS)

    fun hasContacts(context: Context): Boolean = has(context, Manifest.permission.READ_CONTACTS)

    /**
     * Permiso especial (no se concede con el diálogo normal, hay que llevar al
     * usuario a una pantalla de ajustes): escritura de ajustes del sistema.
     */
    fun canWriteSettings(context: Context): Boolean =
        android.provider.Settings.System.canWrite(context)

    fun canWriteSecureSettings(): Boolean {
        // Escribir ajustes "seguros" (bluetooth, etc.) NO está disponible para
        // apps normales sin privilegios de sistema, ni pidiendo permiso. La app
        // no lo intenta siquiera: sería un fallo silencioso garantizado.
        return false
    }
}
