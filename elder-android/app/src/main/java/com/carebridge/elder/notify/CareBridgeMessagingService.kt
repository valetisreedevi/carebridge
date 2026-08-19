package com.carebridge.elder.notify

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
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

class CareBridgeMessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        val elderId = Pairing.load(this) ?: return

        CoroutineScope(Dispatchers.IO).launch {
            runCatching {
                ApiClient.api.registerDevice(RegisterDeviceBody(elderId, token))
            }
        }
    }

    override fun onMessageReceived(message: RemoteMessage) {
        // The payload carries ids only; the reminder itself is fetched from
        // the API so the phone always shows current state.
        if (message.data["type"] != "MEDICATION_REMINDER") return

        val eventId = message.data["event_id"] ?: return
        showReminder(this, eventId)
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
fun showReminder(context: Context, eventId: String) {
    ensureReminderChannel(context)

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
        .setContentTitle("Medicine time")
        .setContentText("Tap to see your medicine")
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
