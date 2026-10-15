package com.samuelpart.jarvispro.ui.components

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.height
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/**
 * Botón principal de la app.
 *
 * Existe para que el botón "Guardar" de Ajustes mida igual en todas las pantallas
 * sin repetir los modificadores por ahí.
 */
@Composable
fun PrimaryActionButton(
    text: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.height(48.dp),
        contentPadding = PaddingValues(horizontal = 24.dp, vertical = 12.dp),
    ) {
        Text(text)
    }
}
