package com.carebridge.elder.ui

import android.Manifest
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.carebridge.elder.data.ApiClient
import com.carebridge.elder.data.Pairing
import com.carebridge.elder.data.RedeemBody
import com.carebridge.elder.notify.ensureReminderChannel
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Setup only. Once the phone is paired, every real interaction happens in
 * ReminderActivity, launched by a notification.
 */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ensureReminderChannel(this)

        val paired = Pairing.load(this)

        if (paired != null) {
            startActivity(Intent(this, ReminderActivity::class.java))
            finish()
            return
        }

        setContent { PairingScreen() }
    }
}

@Composable
private fun PairingScreen() {
    val context = LocalContext.current
    var code by remember { mutableStateOf("") }
    var status by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    var permissionNote by remember { mutableStateOf<String?>(null) }

    // Everything the phone needs is asked for here, once, while a family
    // member is holding it. An elder woken at 8am must never meet a dialog.
    val askPermissions = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { granted ->
        if (granted[Manifest.permission.POST_NOTIFICATIONS] == false) {
            permissionNote = "Notifications are turned off, so reminders cannot show."
        }
    }

    LaunchedEffect(Unit) {
        val wanted = mutableListOf(Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            wanted += Manifest.permission.POST_NOTIFICATIONS
        }

        val missing = wanted.filter {
            ContextCompat.checkSelfPermission(context, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isNotEmpty()) askPermissions.launch(missing.toTypedArray())

        // Not a runtime permission: Android 14 hands this one out only to
        // clocks and diallers, and everyone else has to be sent to Settings.
        // Skipping it costs nothing visible until the screen is locked, which
        // is the only time it matters.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            val notifications = context.getSystemService(NotificationManager::class.java)
            if (notifications?.canUseFullScreenIntent() == false) {
                permissionNote =
                    "One more: allow CareBridge to show reminders on a locked screen."
                runCatching {
                    context.startActivity(
                        Intent(
                            Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT,
                            Uri.parse("package:${context.packageName}"),
                        )
                    )
                }
            }
        }

        // Doze would otherwise be free to hold a dose until the phone is next
        // picked up, which for an elder asleep at 8am is far too late.
        val power = context.getSystemService(PowerManager::class.java)
        if (power?.isIgnoringBatteryOptimizations(context.packageName) == false) {
            runCatching {
                context.startActivity(
                    Intent(
                        Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                        Uri.parse("package:${context.packageName}"),
                    )
                )
            }
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().padding(28.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("Set up CareBridge", fontSize = 30.sp)

        Text(
            "Enter the code your family gave you.",
            fontSize = 18.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 8.dp, bottom = 24.dp),
        )

        OutlinedTextField(
            value = code,
            onValueChange = { code = it.trim() },
            label = { Text("Code") },
            modifier = Modifier.fillMaxWidth(),
        )

        Button(
            onClick = {
                status = "Pairing…"

                // The code is spent and the phone's address handed over in one
                // call. Nothing is saved until the server has accepted it —
                // saving first meant a mistyped code left the app permanently
                // "paired" to nothing, with no screen anywhere to undo it.
                FirebaseMessaging.getInstance().token
                    .addOnSuccessListener { token ->
                        scope.launch {
                            val paired = withContext(Dispatchers.IO) {
                                runCatching {
                                    ApiClient.api.redeemPairingCode(
                                        RedeemBody(
                                            code = code,
                                            fcmToken = token,
                                            platform = "ANDROID",
                                            label = Build.MODEL,
                                        )
                                    )
                                }
                            }

                            paired.onSuccess { reply ->
                                Pairing.save(context, reply.elderId)
                                status = if (reply.deviceRegistered) {
                                    "Ready. This is ${reply.elderName}'s phone."
                                } else {
                                    "Paired, but this phone cannot be reminded yet."
                                }
                            }
                            paired.onFailure {
                                status = "That code did not work. Ask for a new one."
                            }
                        }
                    }
                    .addOnFailureListener {
                        status = "This phone cannot receive reminders yet."
                    }
            },
            enabled = code.length > 4,
            modifier = Modifier
                .fillMaxWidth()
                .height(68.dp)
                .padding(top = 20.dp),
        ) {
            Text("Pair this phone", fontSize = 22.sp)
        }

        status?.let {
            Text(it, fontSize = 18.sp, modifier = Modifier.padding(top = 16.dp))
        }

        permissionNote?.let {
            Text(it, fontSize = 16.sp, modifier = Modifier.padding(top = 12.dp))
        }
    }
}
