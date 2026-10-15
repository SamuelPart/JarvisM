package com.samuelpart.jarvispro.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle

/**
 * Pantalla principal: la conversación.
 *
 * Toda la lógica vive en el ViewModel; aquí solo se dibuja y se recogen gestos.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ChatScreen(
    viewModel: JarvisViewModel,
    onOpenSettings: () -> Unit,
    onMicPressed: () -> Unit,
) {
    val items by viewModel.items.collectAsStateWithLifecycle()
    val status by viewModel.status.collectAsStateWithLifecycle()
    val busy by viewModel.busy.collectAsStateWithLifecycle()
    val listening by viewModel.listening.collectAsStateWithLifecycle()
    val partial by viewModel.partialText.collectAsStateWithLifecycle()
    val confirmation by viewModel.confirmation.collectAsStateWithLifecycle()

    var draft by remember { mutableStateOf("") }
    val listState = rememberLazyListState()

    // Autoscroll: al llegar un trozo nuevo de texto, baja sola.
    LaunchedEffect(items.size, items.lastOrNull()?.text?.length) {
        if (items.isNotEmpty()) {
            listState.animateScrollToItem(items.lastIndex)
        }
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("JARVIS Pro", fontWeight = FontWeight.SemiBold)
                        Text(
                            text = when {
                                listening -> "Te escucho…"
                                status.isNotBlank() -> status
                                else -> "Solo Gemini · escritura y voz"
                            },
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                },
                actions = {
                    IconButton(onClick = { viewModel.clearChat() }) {
                        Icon(Icons.Filled.Delete, contentDescription = "Borrar conversación")
                    }
                    IconButton(onClick = onOpenSettings) {
                        Icon(Icons.Filled.Settings, contentDescription = "Ajustes")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                    titleContentColor = MaterialTheme.colorScheme.onSurface,
                ),
            )
        },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        Column(modifier = Modifier.fillMaxSize().padding(padding)) {

            if (items.isEmpty()) {
                // `weight(1f)` y no `fillMaxSize()`: si ocupa todo el alto, empuja
                // la barra de escritura fuera de la pantalla.
                EmptyState(
                    modifier = Modifier.weight(1f),
                    onSuggestion = { viewModel.sendMessage(it) },
                )
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier.weight(1f).fillMaxWidth(),
                    contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(items, key = { it.id }) { item ->
                        MessageBubble(item = item, onSpeak = { viewModel.speak(item.text) })
                    }
                }
            }

            // Mientras se dicta, se enseña lo que el reconocedor va entendiendo.
            if (listening) {
                Surface(
                    color = MaterialTheme.colorScheme.secondaryContainer,
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp),
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        modifier = Modifier.padding(12.dp),
                    ) {
                        CircularProgressIndicator(modifier = Modifier.size(16.dp), strokeWidth = 2.dp)
                        Spacer(Modifier.width(12.dp))
                        Text(
                            text = partial.ifBlank { "Habla ahora…" },
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSecondaryContainer,
                        )
                    }
                }
            }

            InputBar(
                draft = draft,
                onDraftChange = { draft = it },
                busy = busy,
                listening = listening,
                onSend = {
                    val text = draft
                    draft = ""
                    viewModel.sendMessage(text)
                },
                onMic = onMicPressed,
                onStop = {
                    viewModel.stopTurn()
                    viewModel.stopVoice()
                },
            )
        }
    }

    confirmation?.let { pending ->
        AlertDialog(
            onDismissRequest = { viewModel.answerConfirmation(false) },
            title = { Text("¿Le dejo hacerlo?") },
            text = {
                Column {
                    Text(
                        text = humanToolName(pending.toolName).replaceFirstChar { it.uppercase() },
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                    if (pending.argsPreview.isNotBlank()) {
                        Spacer(Modifier.height(6.dp))
                        Text(
                            text = pending.argsPreview,
                            style = MaterialTheme.typography.bodySmall,
                            fontFamily = FontFamily.Monospace,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                    Spacer(Modifier.height(10.dp))
                    Text(text = pending.description, style = MaterialTheme.typography.bodyMedium)
                    Spacer(Modifier.height(10.dp))
                    Text(
                        text = "Nivel: ${pending.tier.label}" +
                            if (pending.tier.rank >= 3) " · esto no se puede deshacer" else "",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            },
            confirmButton = { TextButton(onClick = { viewModel.answerConfirmation(true) }) { Text("Permitir") } },
            dismissButton = { TextButton(onClick = { viewModel.answerConfirmation(false) }) { Text("Cancelar") } },
        )
    }
}

@Composable
private fun EmptyState(modifier: Modifier = Modifier, onSuggestion: (String) -> Unit) {
    val suggestions = listOf(
        "Pon una alarma a las 6:30",
        "Abre WhatsApp",
        "¿Cuánta batería me queda?",
        "Sube el volumen al 70 %",
        "Enciende la linterna",
    )
    Column(
        // Desplazable para que en pantallas pequeñas (o con el teclado abierto) se
        // pueda llegar a los botones en vez de quedarse cortados.
        modifier = modifier
            .fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("JARVIS", style = MaterialTheme.typography.displaySmall, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Text(
            text = "Escribe o usa el micrófono. Puedo hablar con Gemini y tocar " +
                "tu teléfono: alarmas, apps, volumen, linterna, avisos…",
            style = MaterialTheme.typography.bodyMedium,
            textAlign = TextAlign.Center,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(24.dp))
        Text(
            text = "Prueba con:",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
        Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(8.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            suggestions.forEach { suggestion ->
                FilledTonalButton(onClick = { onSuggestion(suggestion) }) { Text(suggestion) }
            }
        }
    }
}

@Composable
private fun MessageBubble(item: ChatItem, onSpeak: () -> Unit) {
    val isUser = item.role == ChatItem.Role.USER
    val alignment = if (isUser) Alignment.End else Alignment.Start

    if (item.role == ChatItem.Role.NOTICE) {
        Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
            Text(
                text = item.text,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(horizontal = 24.dp),
            )
        }
        return
    }

    Box(modifier = Modifier.fillMaxWidth(), contentAlignment = alignment) {
        Surface(
            color = when (item.role) {
                ChatItem.Role.USER -> MaterialTheme.colorScheme.primaryContainer
                ChatItem.Role.TOOL -> MaterialTheme.colorScheme.surfaceVariant
                ChatItem.Role.ERROR -> MaterialTheme.colorScheme.errorContainer
                else -> MaterialTheme.colorScheme.surfaceContainer
            },
            shape = RoundedCornerShape(
                topStart = 16.dp,
                topEnd = 16.dp,
                bottomStart = if (isUser) 16.dp else 4.dp,
                bottomEnd = if (isUser) 4.dp else 16.dp,
            ),
            modifier = Modifier.fillMaxWidth(0.92f),
        ) {
            Column(modifier = Modifier.padding(12.dp)) {
                if (item.role == ChatItem.Role.TOOL) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = if (item.ok) "✔" else "✖",
                            color = if (item.ok) MaterialTheme.colorScheme.primary
                            else MaterialTheme.colorScheme.error,
                        )
                        Spacer(Modifier.width(6.dp))
                        Text(
                            text = humanToolName(item.toolName.orEmpty()),
                            style = MaterialTheme.typography.labelMedium,
                            fontWeight = FontWeight.SemiBold,
                        )
                        item.tier?.let { tier ->
                            Spacer(Modifier.width(8.dp))
                            Text(
                                text = tier.label,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                        }
                    }
                    Spacer(Modifier.height(4.dp))
                }

                Text(
                    text = item.text.ifBlank { if (item.streaming) "…" else "" },
                    style = MaterialTheme.typography.bodyMedium,
                    color = when (item.role) {
                        ChatItem.Role.USER -> MaterialTheme.colorScheme.onPrimaryContainer
                        ChatItem.Role.ERROR -> MaterialTheme.colorScheme.onErrorContainer
                        else -> MaterialTheme.colorScheme.onSurface
                    },
                )

                if (item.role == ChatItem.Role.JARVIS && item.text.isNotBlank() && !item.streaming) {
                    TextButton(onClick = onSpeak, contentPadding = PaddingValues(0.dp)) {
                        Text("Leer en voz alta", style = MaterialTheme.typography.labelSmall)
                    }
                }
            }
        }
    }
}

@Composable
private fun InputBar(
    draft: String,
    onDraftChange: (String) -> Unit,
    busy: Boolean,
    listening: Boolean,
    onSend: () -> Unit,
    onMic: () -> Unit,
    onStop: () -> Unit,
) {
    Surface(color = MaterialTheme.colorScheme.surface, tonalElevation = 3.dp) {
        Column(modifier = Modifier.fillMaxWidth().padding(12.dp)) {
            // Nada de `horizontalScroll` en este Row: un hijo con `weight` dentro
            // de un contenedor desplazable recibe medidas infinitas y Compose
            // lanza una excepción en tiempo de ejecución.
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = draft,
                    onValueChange = onDraftChange,
                    modifier = Modifier.weight(1f).heightIn(min = 56.dp),
                    placeholder = { Text("Pídele algo a Jarvis…") },
                    maxLines = 4,
                    shape = RoundedCornerShape(14.dp),
                )
                Spacer(Modifier.width(8.dp))
                Column(verticalArrangement = Arrangement.Center) {
                    IconButton(
                        onClick = onSend,
                        enabled = !busy && draft.isNotBlank(),
                    ) {
                        Icon(Icons.Filled.Send, contentDescription = "Enviar")
                    }
                    FilledTonalButton(
                        onClick = if (busy) onStop else onMic,
                        contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
                    ) {
                        Text(
                            text = when {
                                busy -> "Parar"
                                listening -> "Listo"
                                else -> "Hablar"
                            },
                            style = MaterialTheme.typography.labelMedium,
                        )
                    }
                }
            }
        }
    }
}
