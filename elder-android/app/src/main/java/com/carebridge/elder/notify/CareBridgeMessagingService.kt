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

const val REMINDER_CHANNEL_ID = "carebridge_reminders"
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

        if (message.data["type"] != "MEDICATION_REMINDER") return

        val eventId = message.data["event_id"] ?: return
        showReminder(
            context = this,
            eventId = eventId,
            title = message.data["title"],
            body = message.data["body"],
        )
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

        // The channel rings on the alarm stream too, so the phone is audible
        // even in the case where the app never gets to play the recording.
        // NOTE: channel settings are frozen at creation. Changing this line
        // does nothing on a phone that already has the app — uninstall first.
        setSound(
            RingtoneManager.getDefaultUri(RingtoneManager.TYPE_ALARM),
            AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build(),
        )
    }

    context.getSystemService(NotificationManager::class.java)
        .createNotificationChannel(channel)
}

/**
 * A high-priority notification with a full-screen intent.
 *
 * Android decides whether the activity actually takes over the screen: it does
 * when the device is locked, and otherwise the heads-up notification shows.
 * Both paths lead to the same screen, so the elder never has to find the app.
 */
fun showReminder(
    context: Context,
    eventId: String,
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
        putExtra(ReminderActivity.EXTRA_EVENT_ID, eventId)
    }

    val pending = PendingIntent.getActivity(
        context,
        eventId.hashCode(),
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
            .notify(eventId.hashCode(), notification)
    }
}
