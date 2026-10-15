package com.samuelpart.jarvispro.ui

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.samuelpart.jarvispro.data.AppSettings

/**
 * Pantalla de ajustes: clave, modelo, personalidad, voz y permisos peligrosos.
 *
 * Se trabaja sobre una copia (`draft`) y solo se guarda al pulsar el botón: así
 * escribir la clave no dispara nada a medias.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(viewModel: JarvisViewModel, onBack: () -> Unit) {
    val stored by viewModel.settings.collectAsStateWithLifecycle()
    var draft by remember(stored) { mutableStateOf(stored) }
    var keyVisible by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val masked = remember(stored.apiKey) { viewModel.maskedKey() }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Ajustes") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Volver")
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.surface,
                ),
            )
        },
        containerColor = MaterialTheme.colorScheme.background,
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            // ---- clave de API -------------------------------------------------
            Text("Clave de la API de Gemini", style = MaterialTheme.typography.titleMedium)
            if (masked.isNotBlank()) {
                Text(
                    text = "Guardada: $masked",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            OutlinedTextField(
                value = draft.apiKey,
                onValueChange = { draft = draft.copy(apiKey = it) },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("Clave (AQ.… o AIza…)") },
                singleLine = true,
                visualTransformation = if (keyVisible) VisualTransformation.None
                else PasswordVisualTransformation(),
                trailingIcon = {
                    TextButton(onClick = { keyVisible = !keyVisible }) {
                        Text(if (keyVisible) "Ocultar" else "Ver")
                    }
                },
            )
            Text(
                text = "Se consigue gratis en aistudio.google.com → Get API key. " +
                    "Se guarda solo en este teléfono y no entra en copias de seguridad. " +
                    "Un teléfono con root podría leerla: para uso personal es asumible, " +
                    "para publicar la app habría que cifrarla con Keystore.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            HorizontalDivider()

            // ---- modelo -------------------------------------------------------
            Text("Modelo", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = draft.model,
                onValueChange = { draft = draft.copy(model = it) },
                modifier = Modifier.fillMaxWidth(),
                label = { Text("Identificador del modelo") },
                singleLine = true,
            )
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                AppSettings.SUGGESTED_MODELS.forEach { model ->
                    FilterChip(
                        selected = draft.model == model,
                        onClick = { draft = draft.copy(model = model) },
                        label = { Text(model, style = MaterialTheme.typography.labelSmall) },
                    )
                }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { viewModel.testConnection() }) { Text("Probar conexión") }
                OutlinedButton(onClick = { viewModel.listModels() }) { Text("Ver modelos") }
            }

            HorizontalDivider()

            // ---- comportamiento ------------------------------------------------
            Text("Comportamiento", style = MaterialTheme.typography.titleMedium)

            LabeledSwitch(
                label = "Leer las respuestas en voz alta",
                checked = draft.speakReplies,
                onChange = { draft = draft.copy(speakReplies = it) },
            )
            LabeledSwitch(
                label = "Mostrar la respuesta mientras se escribe",
                checked = draft.streamResponses,
                onChange = { draft = draft.copy(streamResponses = it) },
            )
            LabeledSwitch(
                label = "Guardar el historial en el teléfono",
                checked = draft.saveHistory,
                onChange = { draft = draft.copy(saveHistory = it) },
            )

            Text("Creatividad: ${"%.1f".format(draft.temperature)}", style = MaterialTheme.typography.labelMedium)
            Slider(
                value = draft.temperature,
                onValueChange = { draft = draft.copy(temperature = it) },
                valueRange = 0f..1f,
                steps = 9,
            )

            HorizontalDivider()

            // ---- voz -----------------------------------------------------------
            Text("Idioma de la voz", style = MaterialTheme.typography.titleMedium)
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                AppSettings.VOICE_LANGUAGES.forEach { language ->
                    FilterChip(
                        selected = draft.voiceLanguage == language,
                        onClick = { draft = draft.copy(voiceLanguage = language) },
                        label = { Text(language) },
                    )
                }
            }

            HorizontalDivider()

            // ---- acciones del teléfono ------------------------------------------
            Text("Acciones del teléfono", style = MaterialTheme.typography.titleMedium)
            LabeledSwitch(
                label = "Pedirme permiso antes de CADA acción",
                checked = draft.confirmEveryAction,
                onChange = { draft = draft.copy(confirmEveryAction = it) },
            )
            LabeledSwitch(
                label = "Permitir enviar SMS (no se puede deshacer)",
                checked = draft.allowSms,
                onChange = { draft = draft.copy(allowSms = it) },
            )
            Text(
                text = "Con el interruptor de SMS apagado, Jarvis no puede enviar " +
                    "mensajes: ni siquiera sabe que esa herramienta existe. Aun " +
                    "activándolo, siempre pedirá confirmación antes de enviar.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            OutlinedButton(onClick = {
                // Pantalla de permisos de ESTA app, para el brillo y el micrófono.
                val intent = Intent(
                    Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.fromParts("package", context.packageName, null),
                )
                context.startActivity(intent)
            }) { Text("Abrir permisos de la app") }

            HorizontalDivider()

            // ---- personalidad ----------------------------------------------------
            Text("Personalidad (instrucciones del sistema)", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = draft.systemPrompt,
                onValueChange = { draft = draft.copy(systemPrompt = it) },
                modifier = Modifier.fillMaxWidth().height(200.dp),
                label = { Text("System prompt") },
            )
            TextButton(onClick = {
                draft = draft.copy(systemPrompt = AppSettings.DEFAULT_SYSTEM_PROMPT)
            }) { Text("Restaurar el de fábrica") }

            HorizontalDivider()

            // ---- guardar / borrar --------------------------------------------------
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                com.samuelpart.jarvispro.ui.components.PrimaryActionButton(
                    text = "Guardar",
                    onClick = {
                        viewModel.saveSettings(draft.copy(apiKey = draft.apiKey.trim()))
                        onBack()
                    },
                )
                OutlinedButton(onClick = { viewModel.clearChat() }) { Text("Borrar conversación") }
            }

            Spacer(Modifier.height(24.dp))
            Text(
                text = "JARVIS Pro · solo API de Gemini · " +
                    "la conversación se borra desde el icono de la papelera en el chat",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun LabeledSwitch(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(text = label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange)
    }
}
