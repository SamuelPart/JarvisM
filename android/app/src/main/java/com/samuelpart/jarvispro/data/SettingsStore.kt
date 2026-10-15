package com.samuelpart.jarvispro.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Persistencia de los ajustes.
 *
 * Se usa `SharedPreferences` del almacén privado de la app, no un fichero propio
 * ni una base de datos: son 11 valores y así no hace falta ninguna dependencia
 * más (Room arrastraría un procesador de anotaciones y otra versión que acertar).
 *
 * Sobre la clave de API: se guarda aquí y se expone a la interfaz. La app tiene
 * `allowBackup=false` y reglas de extracción vacías, así que la clave no entra en
 * copias de seguridad ni se transfiere a otro dispositivo. Aun así, es un
 * almacén sin cifrar: un teléfono con root puede leerla. Por eso la interfaz la
 * muestra enmascarada y el README lo dice sin adornos.
 */
class SettingsStore(context: Context) {

    private val prefs = context.applicationContext
        .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    private val _settings = MutableStateFlow(read())
    val settings: StateFlow<AppSettings> = _settings.asStateFlow()

    fun read(): AppSettings {
        val defaults = AppSettings()
        return AppSettings(
            apiKey = prefs.getString(KEY_API_KEY, defaults.apiKey).orEmpty(),
            model = prefs.getString(KEY_MODEL, defaults.model)?.takeIf { it.isNotBlank() }
                ?: defaults.model,
            systemPrompt = prefs.getString(KEY_SYSTEM_PROMPT, defaults.systemPrompt)
                ?.takeIf { it.isNotBlank() } ?: defaults.systemPrompt,
            temperature = prefs.getFloat(KEY_TEMPERATURE, defaults.temperature),
            maxOutputTokens = prefs.getInt(KEY_MAX_TOKENS, defaults.maxOutputTokens),
            speakReplies = prefs.getBoolean(KEY_SPEAK, defaults.speakReplies),
            streamResponses = prefs.getBoolean(KEY_STREAM, defaults.streamResponses),
            confirmEveryAction = prefs.getBoolean(KEY_CONFIRM_ALL, defaults.confirmEveryAction),
            allowSms = prefs.getBoolean(KEY_ALLOW_SMS, defaults.allowSms),
            saveHistory = prefs.getBoolean(KEY_SAVE_HISTORY, defaults.saveHistory),
            voiceLanguage = prefs.getString(KEY_VOICE_LANG, defaults.voiceLanguage)
                ?: defaults.voiceLanguage,
        )
    }

    fun write(settings: AppSettings) {
        prefs.edit()
            .putString(KEY_API_KEY, settings.apiKey.trim())
            .putString(KEY_MODEL, settings.model.trim())
            .putString(KEY_SYSTEM_PROMPT, settings.systemPrompt)
            .putFloat(KEY_TEMPERATURE, settings.temperature)
            .putInt(KEY_MAX_TOKENS, settings.maxOutputTokens)
            .putBoolean(KEY_SPEAK, settings.speakReplies)
            .putBoolean(KEY_STREAM, settings.streamResponses)
            .putBoolean(KEY_CONFIRM_ALL, settings.confirmEveryAction)
            .putBoolean(KEY_ALLOW_SMS, settings.allowSms)
            .putBoolean(KEY_SAVE_HISTORY, settings.saveHistory)
            .putString(KEY_VOICE_LANG, settings.voiceLanguage)
            .apply()
        _settings.value = read()
    }

    /**
     * Enmascara la clave para poder mostrarla en pantalla sin exponerla entera:
     * `AQ.Ab8RN6IY8…` -> `AQ.Ab8R…9f2c` (prefijo y sufijo, nada del medio).
     */
    fun maskedKey(): String {
        val key = _settings.value.apiKey
        if (key.length < 12) return if (key.isEmpty()) "" else "•".repeat(key.length)
        return "${key.take(7)}…${key.takeLast(4)} (${key.length} caracteres)"
    }

    private companion object {
        const val PREFS_NAME = "jarvis_settings"
        const val KEY_API_KEY = "api_key"
        const val KEY_MODEL = "model"
        const val KEY_SYSTEM_PROMPT = "system_prompt"
        const val KEY_TEMPERATURE = "temperature"
        const val KEY_MAX_TOKENS = "max_output_tokens"
        const val KEY_SPEAK = "speak_replies"
        const val KEY_STREAM = "stream_responses"
        const val KEY_CONFIRM_ALL = "confirm_all"
        const val KEY_ALLOW_SMS = "allow_sms"
        const val KEY_SAVE_HISTORY = "save_history"
        const val KEY_VOICE_LANG = "voice_language"
    }
}
