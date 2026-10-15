package com.samuelpart.jarvispro

import android.Manifest
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.viewmodel.compose.viewModel
import com.samuelpart.jarvispro.agent.Perms
import com.samuelpart.jarvispro.ui.ChatScreen
import com.samuelpart.jarvispro.ui.JarvisViewModel
import com.samuelpart.jarvispro.ui.SettingsScreen
import com.samuelpart.jarvispro.ui.theme.JarvisTheme

/**
 * Única actividad de la app: alterna entre el chat y los ajustes.
 *
 * No se usa Navigation Compose a propósito: son dos pantallas y un booleano. Meter
 * una librería de navegación para esto sería más código y más versiones que acertar.
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            JarvisTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color = MaterialTheme.colorScheme.background,
                ) {
                    val viewModel: JarvisViewModel = viewModel()
                    JarvisRoot(viewModel)
                }
            }
        }
    }
}

@Composable
private fun JarvisRoot(viewModel: JarvisViewModel) {
    var showSettings by remember { mutableStateOf(false) }
    val context = LocalContext.current

    // El permiso de micrófono se pide la primera vez que se pulsa "Hablar", no al
    // abrir la app: pedir permisos antes de que sirvan para algo espanta.
    val micPermission = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            viewModel.startVoice()
        } else {
            viewModel.notifyUser(
                "Sin permiso de micrófono no puedo escucharte. Puedes concederlo en " +
                    "Ajustes de la app → Permisos, o escribir el mensaje.",
            )
        }
    }

    if (showSettings) {
        SettingsScreen(viewModel = viewModel, onBack = { showSettings = false })
    } else {
        ChatScreen(
            viewModel = viewModel,
            onOpenSettings = { showSettings = true },
            onMicPressed = {
                if (Perms.hasMic(context)) viewModel.startVoice()
                else micPermission.launch(Manifest.permission.RECORD_AUDIO)
            },
        )
    }
}
