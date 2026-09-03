package com.carebridge.elder.ui

import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.core.app.NotificationManagerCompat

/**
 * What the phone is actually permitting, in the family's words.
 *
 * Every one of these fails silently. A blocked full-screen intent still rings,
 * still shows a notification, and still works perfectly the moment you unlock
 * the phone to check — so the only visible symptom is an elder who has to
 * unlock, scroll and tap, which is the thing the app exists to avoid. This
 * screen exists so nobody has to guess which switch is off.
 */
data class Check(
    val title: String,
    val why: String,
    val ok: Boolean,
    val fix: Intent?,
)

private fun appIntent(action: String, context: Context) =
    Intent(action, Uri.parse("package:${context.packageName}"))

fun setupChecks(context: Context): List<Check> {
    val checks = mutableListOf<Check>()

    val notifications = context.getSystemService(NotificationManager::class.java)

    checks += Check(
        title = "Show reminders",
        why = "Without this nothing appears at all.",
        ok = NotificationManagerCompat.from(context).areNotificationsEnabled(),
        fix = Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName),
    )

    // The one that decides whether the screen wakes on its own.
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
        checks += Check(
            title = "Wake the locked screen",
            why = "Off means she must unlock and tap the notification herself.",
            ok = notifications?.canUseFullScreenIntent() == true,
            fix = appIntent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, context),
        )
    }

    // Oppo, OnePlus, Xiaomi and Vivo gate background screen-raising on this
    // even when Android itself would allow it.
    checks += Check(
        title = "Open over other apps",
        why = "Some phones block the reminder screen without it.",
        ok = Settings.canDrawOverlays(context),
        fix = appIntent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, context),
    )

    val power = context.getSystemService(PowerManager::class.java)
    checks += Check(
        title = "Run without battery limits",
        why = "Otherwise a dose can be held back until the phone is picked up.",
        ok = power?.isIgnoringBatteryOptimizations(context.packageName) == true,
        fix = appIntent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, context),
    )

    return checks
}
