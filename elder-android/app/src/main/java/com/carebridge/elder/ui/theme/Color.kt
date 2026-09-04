package com.carebridge.elder.ui.theme

import androidx.compose.ui.graphics.Color

/**
 * The single source of the app's colour, matching the web client's tokens
 * digit for digit (`:root` in frontend/src/index.css).
 *
 * Before this there were three CareBridge greens — #12695A on the launcher,
 * #1B7A4B in the app, #0F6B5C on the web — and no theme at all, which is why
 * every control the app did not colour by hand came out stock Material purple.
 */
val Brand = Color(0xFF0F6B5C)
val BrandSoft = Color(0xFFE4EFEC)
val BrandInk = Color(0xFF0A4F43)

val Paper = Color(0xFFFAF7F2)
val Card = Color(0xFFFFFFFF)
val Ink = Color(0xFF1F1A17)
val InkSoft = Color(0xFF4A423C)
val Muted = Color(0xFF7A706A)
val Line = Color(0xFFE8E1D9)
val LineStrong = Color(0xFFD6CDC3)

val Warn = Color(0xFF97561B)
val Bad = Color(0xFF9B2226)
