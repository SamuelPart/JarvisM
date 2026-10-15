package com.samuelpart.jarvispro

import com.samuelpart.jarvispro.agent.Decision
import com.samuelpart.jarvispro.agent.Policy
import com.samuelpart.jarvispro.agent.RiskTier
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * La política de riesgos es lo que separa un asistente útil de uno que hace
 * barbaridades. Se prueba entera, porque es pura y barata de probar.
 */
class PolicyTest {

    @Test
    fun `las acciones irreversibles siempre piden confirmacion`() {
        val allowed = Policy.decide(RiskTier.T3, confirmEveryAction = false)
        val strict = Policy.decide(RiskTier.T3, confirmEveryAction = true)

        assertEquals(Decision.CONFIRM, allowed)
        assertEquals(Decision.CONFIRM, strict)
    }

    @Test
    fun `sin modo estricto, las acciones normales se ejecutan`() {
        assertEquals(Decision.ALLOW, Policy.decide(RiskTier.T0, false))
        assertEquals(Decision.ALLOW, Policy.decide(RiskTier.T1, false))
        assertEquals(Decision.ALLOW, Policy.decide(RiskTier.T2, false))
    }

    @Test
    fun `con modo estricto, lo externo y lo irreversible piden permiso`() {
        assertEquals(Decision.ALLOW, Policy.decide(RiskTier.T0, true))
        assertEquals(Decision.ALLOW, Policy.decide(RiskTier.T1, true))
        assertEquals(Decision.CONFIRM, Policy.decide(RiskTier.T2, true))
        assertEquals(Decision.CONFIRM, Policy.decide(RiskTier.T3, true))
    }

    @Test
    fun `los niveles se ordenan por rango`() {
        assertTrue(RiskTier.T0.rank < RiskTier.T1.rank)
        assertTrue(RiskTier.T1.rank < RiskTier.T2.rank)
        assertTrue(RiskTier.T2.rank < RiskTier.T3.rank)
    }

    @Test
    fun `acepta direcciones web normales`() {
        assertTrue(Policy.isSafeUrl("https://www.google.com"))
        assertTrue(Policy.isSafeUrl("http://ejemplo.local/pagina"))
        assertTrue("sin esquema se asume https", Policy.isSafeUrl("google.com"))
    }

    @Test
    fun `rechaza esquemas peligrosos`() {
        assertFalse(Policy.isSafeUrl("javascript:alert(1)"))
        assertFalse(Policy.isSafeUrl("file:///etc/passwd"))
        assertFalse(Policy.isSafeUrl("intent://evilscheme#Intent;end"))
        assertFalse(Policy.isSafeUrl("content://com.android.contacts/data"))
        assertFalse(Policy.isSafeUrl("data:text/html,<script>x</script>"))
    }

    @Test
    fun `rechaza direcciones vacias`() {
        assertFalse(Policy.isSafeUrl(""))
        assertFalse(Policy.isSafeUrl("   "))
    }

    @Test
    fun `la comparacion de esquema no distingue mayusculas`() {
        assertTrue(Policy.isSafeUrl("HTTPS://WWW.GOOGLE.COM"))
        assertFalse(Policy.isSafeUrl("JavaScript:alert(1)"))
    }
}
