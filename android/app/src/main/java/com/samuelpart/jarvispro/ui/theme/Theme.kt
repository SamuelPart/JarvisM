package com.samuelpart.jarvispro.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * Paleta "reactor" de Jarvis: azules fríos sobre un fondo casi negro.
 *
 * Es un esquema oscuro fijo, sin seguir el tema del sistema: la app se ve como
 * Jarvis a propósito. Si algún día se quiere modo claro, aquí es donde se añade
 * un `lightColorScheme` y una condición.
 */
private val JarvisColors = darkColorScheme(
    primary = Color(0xFF57C8FF),
    onPrimary = Color(0xFF00243A),
    primaryContainer = Color(0xFF08405F),
    onPrimaryContainer = Color(0xFFCDEBFF),
    secondary = Color(0xFF8FD0F0),
    onSecondary = Color(0xFF00243A),
    secondaryContainer = Color(0xFF1B3A4B),
    onSecondaryContainer = Color(0xFFCDEBFF),
    tertiary = Color(0xFF9CCFEA),
    background = Color(0xFF070B12),
    onBackground = Color(0xFFE6F1FB),
    surface = Color(0xFF101826),
    onSurface = Color(0xFFE6F1FB),
    surfaceVariant = Color(0xFF1B2637),
    onSurfaceVariant = Color(0xFFB6C4D6),
    surfaceContainer = Color(0xFF141E2C),
    outline = Color(0xFF3D4A5C),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
    errorContainer = Color(0xFF93000A),
    onErrorContainer = Color(0xFFFFDAD6),
)

@Composable
fun JarvisTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = JarvisColors, content = content)
}
