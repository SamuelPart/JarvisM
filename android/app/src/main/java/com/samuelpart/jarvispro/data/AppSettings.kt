package com.samuelpart.jarvispro.data

/** Todo lo configurable de la app. Se guarda en las preferencias del teléfono. */
data class AppSettings(
    val apiKey: String = "",
    val model: String = DEFAULT_MODEL,
    val systemPrompt: String = DEFAULT_SYSTEM_PROMPT,
    /** 0 = respuestas siempre iguales, 1 = creativo. 0.4 va bien para un asistente. */
    val temperature: Float = 0.4f,
    val maxOutputTokens: Int = 2048,
    val speakReplies: Boolean = false,
    val streamResponses: Boolean = true,
    /** Si está activo, incluso abrir una app pide confirmación. */
    val confirmEveryAction: Boolean = false,
    /** Enviar SMS es irreversible: apagado hasta que el usuario lo active. */
    val allowSms: Boolean = false,
    val saveHistory: Boolean = true,
    val voiceLanguage: String = "es-ES",
) {
    val isConfigured: Boolean get() = apiKey.isNotBlank()

    companion object {
        /** Modelo por defecto: rápido y con cuota gratuita razonable. */
        const val DEFAULT_MODEL = "gemini-3.8-flash"

        /**
         * Sugerencias para el desplegable de Ajustes. No es una lista cerrada: el
         * campo es editable y hay un botón "Ver modelos disponibles" que pregunta
         * a la API cuáles existen para tu clave, que es la única fuente fiable
         * (Google rota nombres y cuotas con frecuencia).
         */
        val SUGGESTED_MODELS = listOf(
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3-flash-preview",
            "gemini-2.5-flash-lite",
        )

        val VOICE_LANGUAGES = listOf("es-ES", "es-MX", "es-AR", "en-US")

        /**
         * Personalidad de Jarvis. Se envía como `systemInstruction`.
         *
         * La parte de herramientas importa más de lo que parece: el modelo decide
         * cuándo llamar a una función, así que hay que decirle explícitamente que
         * use las herramientas para tocar el teléfono en vez de inventarse pasos.
         */
        val DEFAULT_SYSTEM_PROMPT = """
            Eres Jarvis, el asistente personal del usuario en su teléfono Android.
            Hablas en español, con tono formal pero cercano, y vas al grano: no
            repitas la pregunta ni des rodeos.

            Cómo usas las herramientas:
            - Cuando el usuario pida algo que implique su teléfono (abrir una app,
              poner una alarma, cambiar el volumen, encender la linterna, enviar un
              mensaje), usa la herramienta correspondiente en vez de explicarle
              cómo hacerlo a mano.
            - Si te falta un dato imprescindible (por ejemplo, a qué hora poner la
              alarma), pregúntalo antes de llamar a la herramienta.
            - Solo dispones de las herramientas que te aparecen en esta sesión. Si
              necesitas algo que no está en la lista, dilo con claridad y ofrece la
              alternativa manual.

            Cómo hablas:
            - Respuestas cortas salvo que te pidan detalle. Cuando las respuestas se
              lean en voz alta, evita listas, tablas y símbolos raros.
            - Si no sabes algo o no puedes hacerlo, dilo sin inventarte nada.
        """.trimIndent()
    }
}
