package com.carebridge.elder.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

/**
 * Wraps both activities so Material's own defaults are CareBridge's.
 *
 * The app had no theme. Every control that was not hand-coloured therefore
 * drew itself in Material 3's baseline purple: the pairing field's focus ring
 * and label, both buttons on the setup screen, and — on camera — the outline
 * of "Remind me later" beside a dose. Colouring those at the call site fixes
 * the ones somebody remembered; a theme fixes the ones nobody has drawn yet.
 *
 * Light only, deliberately. The elder screen is a warm paper surface that is
 * legible at arm's length in a lit room at eight in the morning, and every
 * value on it was chosen against that paper. A dark scheme would invert
 * thirteen of them into contrast nobody has checked, on the one screen where
 * being hard to read is the whole failure.
 */
private val CareBridgeColors = lightColorScheme(
    primary = Brand,
    onPrimary = Paper,
    primaryContainer = BrandSoft,
    onPrimaryContainer = BrandInk,

    secondary = Brand,
    onSecondary = Paper,
    secondaryContainer = BrandSoft,
    onSecondaryContainer = BrandInk,

    tertiary = Warn,
    onTertiary = Paper,

    background = Paper,
    onBackground = Ink,
    surface = Card,
    onSurface = Ink,
    surfaceVariant = BrandSoft,
    onSurfaceVariant = InkSoft,

    outline = LineStrong,
    outlineVariant = Line,

    error = Bad,
    onError = Paper,
)

@Composable
fun CareBridgeTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = CareBridgeColors, content = content)
}
