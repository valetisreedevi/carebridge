package com.carebridge.elder.notify

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.RingtoneManager
import android.os.Build
import android.provider.Settings
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.carebridge.elder.R
import com.carebridge.elder.data.ApiClient
import com.carebridge.elder.data.Pairing
import com.carebridge.elder.data.RegisterDeviceBody
import com.carebridge.elder.ui.ReminderActivity
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

// Bumped from "carebridge_reminders". A channel's sound, importance and
// vibration are frozen at creation, so the only way to change any of them on a
// phone that already has the app is a new id. The old one is deleted below so
// it stops appearing in the system settings screen.
const val REMINDER_CHANNEL_ID = "carebridge_reminders_v2"
private const val LEGACY_REMINDER_CHANNEL_ID = "carebridge_reminders"

/**
 * One id for every reminder, on purpose.
 *
 * It used to be the event id's hash, so three medicines due at 8pm stacked
 * three notifications and rang three alarm tones over each other. They are one
 * moment in the elder's evening, and they get one notification. It also makes
 * the notification addressable: the activity can cancel it by id the instant
 * it takes over the screen, which is what stops the alarm playing underneath
 * the family's recorded voice.
 */
const val REMINDER_NOTIFICATION_ID = 1

private const val TAG = "CareBridge"

class CareBridgeMessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        // Needs the elder's own credentials, which this build does not hold,
        // so a rotated token cannot re-register itself yet. Rare enough to
        // live with; re-pairing fixes it. Logged so it is never a mystery.
        Pairing.load(this) ?: return

        CoroutineScope(Dispatchers.IO).launch {
            val outcome = runCatching {
                ApiClient.api.registerDevice(RegisterDeviceBody(token))
            }
            Log.i(TAG, "token_rotated re_registered=${outcome.isSuccess}")
        }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        // Reached only for a data-only message. Anything carrying a
        // notification block is drawn by the tray and never arrives here while
        // the phone is asleep, which is the whole reason the backend now sends
        // Android devices a bare data payload.
        Log.i(TAG, "fcm_received type=${message.data["type"]} keys=${message.data.keys}")

        when (message.data["type"]) {
            "MEDICATION_REMINDER" -> {
                val eventId = message.data["event_id"] ?: return
                showReminder(
                    context = this,
                    eventId = eventId,
                    title = message.data["title"],
                    body = message.data["body"],
                )
            }

            // The family's "is this phone working?" button. Data-only messages
            // draw nothing by themselves, so without this the phone stays
            // silent and the answer looks like no.
            "SELF_TEST" -> showPlainNotice(
                context = this,
                title = message.data["title"] ?: "CareBridge is working",
                body = message.data["body"] ?: "Nothing to do.",
            )
        }
    }
}

fun ensureReminderChannel(context: Context) {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return

    val channel = NotificationChannel(
        REMINDER_CHANNEL_ID,
        context.getString(R.string.reminder_channel_name),
        NotificationManager.IMPORTANCE_HIGH,
    ).apply {
        description = context.getString(R.string.reminder_channel_description)
        enableVibration(true)
        lockscreenVisibility = Notification.VISIBILITY_PUBLIC

        // A notification tone carried on alarm ATTRIBUTES: short asset, alarm
        // routing. The attributes are what Android gates on, so this still
        // sounds through silent, vibrate and Do Not Disturb — which is the
        // whole reason it was on the alarm stream in the first place.
        //
        // The asset changed from TYPE_ALARM because an alarm tone is a long,
        // internally looping file. ReminderActivity cancels this notification
        // the moment it starts, but there is a real race between the push
        // arriving and the activity being alive, and losing that race against
        // a looping alarm means seconds of ringing underneath the recording.
        // A notification tone is over in about a second, so the worst case is
        // a blip rather than a minute of noise.
        //
        // Deliberately NOT silent: when "Display over other apps" is refused
        // and the full-screen intent is withheld, this sound is the only thing
        // that reaches her, and silence there is a missed dose.
        setSound(
            RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION),
            AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build(),
        )
    }

    val manager = context.getSystemService(NotificationManager::class.java)
    // Leaves no stale, still-loud channel behind in the settings screen.
    runCatching { manager.deleteNotificationChannel(LEGACY_REMINDER_CHANNEL_ID) }
    manager.createNotificationChannel(channel)
}

/**
 * The same reminder the server sends, raised locally a few seconds from now.
 *
 * Lets the locked-screen behaviour be tested by one person with one phone,
 * without waiting for a dose or involving the network at all — which is the
 * difference between checking a permission in ten seconds and guessing at it
 * across a whole evening.
 */
fun showTestReminder(context: Context, afterSeconds: Long = 10) {
    android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
        showReminder(context, eventId = null, title = "Medicine time", body = "Test reminder")
    }, afterSeconds * 1000)
}

/** A notification that says something and asks nothing. */
fun showPlainNotice(context: Context, title: String, body: String) {
    ensureReminderChannel(context)

    val notification = NotificationCompat.Builder(context, REMINDER_CHANNEL_ID)
        .setSmallIcon(android.R.drawable.ic_dialog_info)
        .setContentTitle(title)
        .setContentText(body)
        .setPriority(NotificationCompat.PRIORITY_HIGH)
        .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        .setAutoCancel(true)
        .build()

    runCatching {
        NotificationManagerCompat.from(context).notify(title.hashCode(), notification)
    }
}

/**
 * Puts the medicine in front of the elder without her doing anything.
 *
 * Two routes, because one is not reliable enough to rest a medication
 * reminder on:
 *
 *  - A notification with a full-screen intent. Android raises it over the
 *    lock screen — but only if it has granted USE_FULL_SCREEN_INTENT, which
 *    since Android 14 it withholds from anything that is not a clock or a
 *    dialler.
 *  - Starting the screen directly. Normally forbidden from the background,
 *    and expressly permitted for an app the user has allowed to display over
 *    other apps. Oppo, OnePlus, Xiaomi and Vivo all gate the first route on
 *    roughly this too, so it is the one that works on the phones that need it.
 *
 * Whichever wins, the elder sees her medicine. If both are blocked she still
 * gets a ringing notification — worse, but not silence.
 */
fun showReminder(
    context: Context,
    eventId: String?,
    title: String? = null,
    body: String? = null,
) {
    ensureReminderChannel(context)

    // Since Android 14 this is not granted on install to anything that is not
    // a clock or a phone dialler. Without it the takeover silently degrades to
    // an ordinary heads-up notification — which looks like success right up
    // until the screen is actually locked.
    val allowed = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
        context.getSystemService(NotificationManager::class.java)
            ?.canUseFullScreenIntent() ?: false
    } else {
        true
    }
    Log.i(TAG, "notification_posting fsi_allowed=$allowed")

    val intent = Intent(context, ReminderActivity::class.java).apply {
        flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        eventId?.let { putExtra(ReminderActivity.EXTRA_EVENT_ID, it) }
    }

    val pending = PendingIntent.getActivity(
        context,
        REMINDER_NOTIFICATION_ID,
        intent,
        PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
    )

    val notification = NotificationCompat.Builder(context, REMINDER_CHANNEL_ID)
        .setSmallIcon(android.R.drawable.ic_dialog_info)
        // The server sends the words, already in the elder's own language.
        // The notification is posted before anything can be fetched, so text
        // decided here could only ever be hardcoded English.
        .setContentTitle(title ?: "Medicine time")
        .setContentText(body ?: "Tap to see your medicine")
        .setPriority(NotificationCompat.PRIORITY_MAX)
        .setCategory(NotificationCompat.CATEGORY_REMINDER)
        .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        .setAutoCancel(true)
        .setContentIntent(pending)
        .setFullScreenIntent(pending, true)
        .build()

    runCatching {
        NotificationManagerCompat.from(context)
            .notify(REMINDER_NOTIFICATION_ID, notification)
    }

    // Then raise the screen ourselves. On a phone that grants the full-screen
    // intent this is redundant and harmless — the activity is single-task, so
    // it does not open twice. On a phone that quietly refuses it, this is the
    // difference between the medicine appearing and an elder being expected
    // to unlock, find a notification and tap it.
    val canOverlay = Settings.canDrawOverlays(context)
    Log.i(TAG, "raising_screen overlay_allowed=$canOverlay")

    if (canOverlay) {
        runCatching { context.startActivity(intent) }
            .onFailure { Log.w(TAG, "direct_start_refused ${it.message}") }
    }
}
