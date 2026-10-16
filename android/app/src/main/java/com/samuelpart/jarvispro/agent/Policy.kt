package com.samuelpart.jarvispro.agent

/**
 * Nivel de riesgo de una acción que puede realizar la app Android:
 *
 *   T0  leer información           → sin efectos, se ejecuta siempre
 *   T1  cambiar algo reversible     → volumen, linterna; se ejecuta y se avisa
 *   T2  salir de la app / externo   → abrir apps, ajustes, navegador; se avisa
 *   T3  irreversible                → enviar un SMS no se puede deshacer
 *
 * Se compara SIEMPRE por `rank`, nunca con `<`/`>` entre enums: Kotlin no los hace
 * comparables. Así el orden de riesgo queda explícito y consistente.
 */
enum class RiskTier(val rank: Int, val label: String) {
    T0(0, "solo lectura"),
    T1(1, "reversible"),
    T2(2, "externo"),
    T3(3, "irreversible"),
}

enum class Decision { ALLOW, CONFIRM, DENY }

/**
 * Decide si una acción se ejecuta sola, pide permiso o se bloquea.
 *
 * Es una función pura a propósito: la política se prueba sin Android y sin
 * teléfono, que es justo lo que hace que se pueda confiar en ella.
 */
object Policy {

    fun decide(tier: RiskTier, confirmEveryAction: Boolean): Decision = when {
        // Lo irreversible nunca se ejecuta sin permiso explícito, ni siquiera con
        // el modo "confiar en todo" activado.
        tier == RiskTier.T3 -> Decision.CONFIRM
        confirmEveryAction && tier.rank >= RiskTier.T2.rank -> Decision.CONFIRM
        else -> Decision.ALLOW
    }

    /** Esquemas de URL que se pueden abrir en el navegador. */
    private val SAFE_SCHEMES = setOf("http", "https")

    /**
     * Bloquea esquemas peligrosos en `open_web`.
     *
     * No es paranoia: `javascript:`, `file://` y `intent:` pueden sacar al usuario
     * de la app o leer ficheros locales, y el texto de la URL lo propone el modelo
     * (que a su vez puede estar influido por lo que diga otra persona en un
     * mensaje). La lista blanca es más segura que la lista negra.
     */
    fun isSafeUrl(url: String): Boolean {
        val trimmed = url.trim()
        if (trimmed.isEmpty()) return false
        // Sin esquema explícito se asume https (el navegador lo hará igual).
        if (!trimmed.contains(":")) return true
        val scheme = trimmed.substringBefore(":").lowercase()
        return scheme in SAFE_SCHEMES
    }

    /**
     * ¿Hace falta permiso de Android para ejecutar esta herramienta ahora mismo?
     * El registro de herramientas solo ofrece las que el usuario ha habilitado.
     */
    fun describe(decision: Decision, tier: RiskTier, action: String): String = when (decision) {
        Decision.ALLOW -> "Ejecutando $action (${tier.label})"
        Decision.CONFIRM -> "Necesito tu permiso para $action (${tier.label})"
        Decision.DENY -> "Bloqueado: $action"
    }
}
