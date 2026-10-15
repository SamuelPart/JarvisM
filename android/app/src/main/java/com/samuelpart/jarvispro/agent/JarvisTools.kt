package com.samuelpart.jarvispro.agent

import com.samuelpart.jarvispro.agent.tools.BatteryTool
import com.samuelpart.jarvispro.agent.tools.ComposeSmsTool
import com.samuelpart.jarvispro.agent.tools.DeviceInfoTool
import com.samuelpart.jarvispro.agent.tools.FlashlightTool
import com.samuelpart.jarvispro.agent.tools.ListAppsTool
import com.samuelpart.jarvispro.agent.tools.MakeCallTool
import com.samuelpart.jarvispro.agent.tools.OpenAppTool
import com.samuelpart.jarvispro.agent.tools.OpenSettingsTool
import com.samuelpart.jarvispro.agent.tools.OpenWebTool
import com.samuelpart.jarvispro.agent.tools.SendSmsTool
import com.samuelpart.jarvispro.agent.tools.SetAlarmTool
import com.samuelpart.jarvispro.agent.tools.SetBrightnessTool
import com.samuelpart.jarvispro.agent.tools.SetReminderTool
import com.samuelpart.jarvispro.agent.tools.SetVolumeTool

/**
 * Catálogo de herramientas que Jarvis puede usar en el teléfono.
 *
 * Están ordenadas por nivel de riesgo para que se vea de un vistazo qué puede
 * hacer solo y qué necesita permiso:
 *
 *   T0 (leer)          device_info, battery_status, list_apps
 *   T1 (reversible)    set_volume, flashlight, set_brightness
 *   T2 (externo)       open_app, open_settings, open_web, make_call, set_alarm,
 *                      set_reminder, compose_sms
 *   T3 (irreversible)  send_sms          ← desactivada por defecto en Ajustes
 *
 * Añadir una herramienta nueva es: crear la clase, meterla aquí, y si tiene
 * efectos, elegir bien su `tier`. No hay que tocar el agente.
 */
object JarvisTools {

    fun registry(): ToolRegistry = ToolRegistry(
        listOf(
            // --- T0: solo consultan -------------------------------------------------
            DeviceInfoTool(),
            BatteryTool(),
            ListAppsTool(),

            // --- T1: efectos locales y reversibles ---------------------------------
            SetVolumeTool(),
            FlashlightTool(),
            SetBrightnessTool(),

            // --- T2: salen de la app o abren algo del sistema ----------------------
            OpenAppTool(),
            OpenSettingsTool(),
            OpenWebTool(),
            MakeCallTool(),
            SetAlarmTool(),
            SetReminderTool(),
            ComposeSmsTool(),

            // --- T3: irreversible --------------------------------------------------
            SendSmsTool(),
        ),
    )
}
