package com.samuelpart.jarvispro.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.samuelpart.jarvispro.agent.AgentEvent
import com.samuelpart.jarvispro.agent.JarvisAgent
import com.samuelpart.jarvispro.agent.JarvisTools
import com.samuelpart.jarvispro.agent.ToolContext
import com.samuelpart.jarvispro.agent.preview
import com.samuelpart.jarvispro.data.AppSettings
import com.samuelpart.jarvispro.data.ChatHistoryStore
import com.samuelpart.jarvispro.data.SettingsStore
import com.samuelpart.jarvispro.data.StoredMessage
import com.samuelpart.jarvispro.gemini.Content
import com.samuelpart.jarvispro.gemini.GeminiClient
import com.samuelpart.jarvispro.gemini.GeminiException
import com.samuelpart.jarvispro.voice.Speaker
import com.samuelpart.jarvispro.voice.VoiceInput
import kotlinx.coroutines.CancellableContinuation
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlin.coroutines.resume

/**
 * Estado y lógica de la interfaz.
 *
 * Reparto de responsabilidades: la interfaz (Compose) solo dibuja lo que hay en
 * estos `StateFlow` y llama a los métodos de aquí. Toda la decisión está en el
 * ViewModel, que sobrevive a los giros de pantalla (por eso la conversación no se
 * pierde al rotar el teléfono).
 */
class JarvisViewModel(application: Application) : AndroidViewModel(application) {

    private val settingsStore = SettingsStore(application)
    private val historyStore = ChatHistoryStore(application)
    private val client = GeminiClient()
    private val registry = JarvisTools.registry()
    private val agent = JarvisAgent(client, registry)

    val speaker = Speaker(application)
    val voice = VoiceInput(application)

    val settings: StateFlow<AppSettings> = settingsStore.settings

    private val _items = MutableStateFlow<List<ChatItem>>(emptyList())
    val items: StateFlow<List<ChatItem>> = _items.asStateFlow()

    /** Texto de estado bajo el título: "Pensando…", "Ejecutando volumen…". */
    private val _status = MutableStateFlow("")
    val status: StateFlow<String> = _status.asStateFlow()

    private val _busy = MutableStateFlow(false)
    val busy: StateFlow<Boolean> = _busy.asStateFlow()

    private val _listening = MutableStateFlow(false)
    val listening: StateFlow<Boolean> = _listening.asStateFlow()

    /** Lo que el reconocedor va entendiendo mientras hablas. */
    private val _partialText = MutableStateFlow("")
    val partialText: StateFlow<String> = _partialText.asStateFlow()

    private val _confirmation = MutableStateFlow<PendingConfirmation?>(null)
    val confirmation: StateFlow<PendingConfirmation?> = _confirmation.asStateFlow()

    /**
     * Contexto real de la conversación para la API: partes con firmas incluidas.
     * Se mantiene en memoria (no se guarda en disco) porque sus datos internos
     * —firmas de pensamiento, ids de llamadas— solo tienen sentido en esta sesión.
     */
    private val protoHistory = mutableListOf<Content>()

    private var turnJob: Job? = null
    private var confirmationContinuation: CancellableContinuation<Boolean>? = null
    private var nextId = 1L

    init {
        loadStoredHistory()
    }

    // -- conversación ------------------------------------------------------- //

    fun sendMessage(text: String) {
        val clean = text.trim()
        if (clean.isEmpty() || _busy.value) return

        val current = settings.value
        if (!current.isConfigured) {
            addItem(ChatItem.Role.NOTICE, "Antes de nada: pega tu clave de Gemini en Ajustes.")
            return
        }

        addItem(ChatItem.Role.USER, clean)
        _busy.value = true
        _status.value = "Pensando…"

        val assistantId = nextId++
        _items.update {
            it + ChatItem(id = assistantId, role = ChatItem.Role.JARVIS, text = "", streaming = true)
        }

        turnJob = viewModelScope.launch {
            val settingsNow = settingsStore.read()
            val sink = JarvisAgent.EventSink { event -> handleEvent(event, assistantId) }
            val confirmer = JarvisAgent.Confirmer { tool, args, tier ->
                askConfirmation(tool.spec.name, tool.spec.description, args.preview(), tier)
            }

            try {
                val finalText = agent.runTurn(
                    settings = settingsNow,
                    history = protoHistory,
                    userText = clean,
                    toolContext = ToolContext(getApplication(), settingsNow),
                    confirmer = confirmer,
                    sink = sink,
                )
                if (settingsNow.speakReplies && finalText.isNotBlank()) {
                    speaker.speak(finalText)
                }
            } catch (e: CancellationException) {
                addItem(ChatItem.Role.NOTICE, "Detenido.")
                throw e
            } catch (e: GeminiException) {
                addItem(ChatItem.Role.ERROR, e.message.orEmpty())
            } catch (e: Exception) {
                addItem(ChatItem.Role.ERROR, "Algo se rompió: ${e.javaClass.simpleName} ${e.message.orEmpty()}")
            } finally {
                _items.update { list -> list.map { if (it.id == assistantId) it.copy(streaming = false) else it } }
                _busy.value = false
                _status.value = ""
                persistHistory()
            }
        }
    }

    /** Corta el turno en curso ("Detener"). */
    fun stopTurn() {
        turnJob?.cancel()
        turnJob = null
        speaker.stop()
        releaseConfirmation(false)
    }

    fun clearChat() {
        stopTurn()
        _items.value = emptyList()
        protoHistory.clear()
        historyStore.clear()
    }

    private suspend fun handleEvent(event: AgentEvent, assistantId: Long) {
        when (event) {
            is AgentEvent.Text -> _items.update { list ->
                list.map { if (it.id == assistantId) it.copy(text = it.text + event.chunk) else it }
            }

            is AgentEvent.ModelTurn -> Unit // El contexto de la API ya lo guarda el agente.

            is AgentEvent.ToolStarted -> _status.value = "Ejecutando ${humanToolName(event.name)}…"

            is AgentEvent.ToolExecuted -> {
                _status.value = ""
                addItem(
                    ChatItem(
                        id = nextId++,
                        role = ChatItem.Role.TOOL,
                        text = event.summary,
                        toolName = event.name,
                        tier = event.tier,
                        ok = event.ok,
                    ),
                )
            }

            is AgentEvent.ToolDenied -> addItem(
                ChatItem.Role.NOTICE,
                "Cancelado: no hice ${humanToolName(event.name)}.",
            )

            is AgentEvent.Notice -> addItem(ChatItem.Role.NOTICE, event.message)

            is AgentEvent.Done -> {
                _status.value = ""
                // Si el modelo solo llamó a herramientas y no dijo nada, se deja
                // claro que el turno terminó en vez de una burbuja vacía.
                _items.update { list ->
                    list.map {
                        if (it.id == assistantId && it.text.isBlank()) {
                            it.copy(text = "Hecho.", streaming = false)
                        } else {
                            it
                        }
                    }
                }
            }
        }
    }

    // -- confirmaciones ----------------------------------------------------- //

    private suspend fun askConfirmation(
        toolName: String,
        description: String,
        argsPreview: String,
        tier: com.samuelpart.jarvispro.agent.RiskTier,
    ): Boolean {
        _status.value = "Esperando tu permiso…"
        val answer = suspendCancellableCoroutine { continuation ->
            confirmationContinuation = continuation
            _confirmation.value = PendingConfirmation(toolName, description, argsPreview, tier)
            continuation.invokeOnCancellation { _confirmation.value = null }
        }
        _confirmation.value = null
        _status.value = ""
        return answer
    }

    fun answerConfirmation(allow: Boolean) {
        releaseConfirmation(allow)
    }

    private fun releaseConfirmation(allow: Boolean) {
        val continuation = confirmationContinuation ?: return
        confirmationContinuation = null
        _confirmation.value = null
        if (continuation.isActive) continuation.resume(allow)
    }

    // -- voz ---------------------------------------------------------------- //

    fun startVoice() {
        if (_listening.value) {
            stopVoice()
            return
        }
        if (!voice.isAvailable()) {
            addItem(
                ChatItem.Role.NOTICE,
                "Este teléfono no tiene reconocimiento de voz disponible. " +
                    "Puedes escribir el mensaje mientras tanto.",
            )
            return
        }
        _partialText.value = ""
        _listening.value = true
        voice.start(
            language = settings.value.voiceLanguage,
            onPartial = { _partialText.value = it },
            onFinal = { text ->
                _listening.value = false
                _partialText.value = ""
                sendMessage(text)
            },
            onError = { message ->
                _listening.value = false
                _partialText.value = ""
                if (message.isNotBlank()) addItem(ChatItem.Role.NOTICE, message)
            },
        )
    }

    fun stopVoice() {
        voice.cancel()
        _listening.value = false
        val partial = _partialText.value.trim()
        _partialText.value = ""
        if (partial.isNotEmpty()) sendMessage(partial)
    }

    fun speak(text: String) {
        if (_busy.value) speaker.stop() else speaker.speak(text)
    }

    // -- ajustes ------------------------------------------------------------ //

    fun saveSettings(newSettings: AppSettings) {
        settingsStore.write(newSettings)
        // El contexto se reinicia a propósito: si cambia el modelo o la
        // personalidad a mitad de charla, arrastrar mensajes viejos da respuestas
        // incoherentes.
        protoHistory.clear()
        addItem(ChatItem.Role.NOTICE, "Ajustes guardados. La conversación empieza de cero.")
    }

    fun maskedKey(): String = settingsStore.maskedKey()

    fun testConnection() {
        val current = settingsStore.read()
        if (!current.isConfigured) {
            addItem(ChatItem.Role.NOTICE, "Primero pega la clave de la API.")
            return
        }
        viewModelScope.launch {
            _status.value = "Probando conexión…"
            try {
                val reply = client.ping(current.apiKey, current.model)
                addItem(
                    ChatItem.Role.NOTICE,
                    "Conexión correcta con «${current.model}». Respondió: «$reply»",
                )
            } catch (e: GeminiException) {
                addItem(ChatItem.Role.ERROR, e.message.orEmpty())
            } finally {
                _status.value = ""
            }
        }
    }

    fun listModels() {
        val current = settingsStore.read()
        if (!current.isConfigured) {
            addItem(ChatItem.Role.NOTICE, "Primero pega la clave de la API.")
            return
        }
        viewModelScope.launch {
            _status.value = "Consultando modelos…"
            try {
                val models = client.listModels(current.apiKey)
                if (models.isEmpty()) {
                    addItem(ChatItem.Role.NOTICE, "La API no devolvió ningún modelo utilizable con esta clave.")
                } else {
                    addItem(
                        ChatItem.Role.NOTICE,
                        "Modelos disponibles (${models.size}):\n" + models.joinToString("\n"),
                    )
                }
            } catch (e: GeminiException) {
                addItem(ChatItem.Role.ERROR, e.message.orEmpty())
            } finally {
                _status.value = ""
            }
        }
    }

    // -- historial ---------------------------------------------------------- //

    private fun loadStoredHistory() {
        if (!settingsStore.read().saveHistory) return
        val stored = historyStore.load()
        if (stored.isEmpty()) return
        _items.value = stored.map { message ->
            ChatItem(
                id = nextId++,
                role = when (message.role) {
                    StoredMessage.ROLE_USER -> ChatItem.Role.USER
                    StoredMessage.ROLE_TOOL -> ChatItem.Role.TOOL
                    StoredMessage.ROLE_ERROR -> ChatItem.Role.ERROR
                    StoredMessage.ROLE_NOTICE -> ChatItem.Role.NOTICE
                    else -> ChatItem.Role.JARVIS
                },
                text = message.text,
                toolName = message.toolName,
                ok = message.ok,
            )
        }
        addItem(
            ChatItem.Role.NOTICE,
            "Recuperada la conversación anterior. El contexto no se reenvía a " +
                "Gemini hasta que escribas de nuevo.",
        )
    }

    private fun persistHistory() {
        if (!settingsStore.read().saveHistory) return
        val stored = _items.value
            // Los avisos y errores son de la sesión, no de la conversación.
            .filter { it.role != ChatItem.Role.NOTICE }
            .map { item ->
                StoredMessage(
                    role = when (item.role) {
                        ChatItem.Role.USER -> StoredMessage.ROLE_USER
                        ChatItem.Role.TOOL -> StoredMessage.ROLE_TOOL
                        ChatItem.Role.ERROR -> StoredMessage.ROLE_ERROR
                        else -> StoredMessage.ROLE_JARVIS
                    },
                    text = item.text,
                    toolName = item.toolName,
                    tier = item.tier?.name,
                    ok = item.ok,
                    timestamp = System.currentTimeMillis(),
                )
            }
        historyStore.save(stored)
    }

    private fun addItem(role: ChatItem.Role, text: String) {
        _items.update { it + ChatItem(id = nextId++, role = role, text = text) }
    }

    /** Aviso suelto desde la interfaz (por ejemplo, permisos denegados). */
    fun notifyUser(message: String) = addItem(ChatItem.Role.NOTICE, message)

    private fun addItem(item: ChatItem) {
        _items.update { it + item }
    }

    override fun onCleared() {
        super.onCleared()
        turnJob?.cancel()
        voice.destroy()
        speaker.shutdown()
    }
}
