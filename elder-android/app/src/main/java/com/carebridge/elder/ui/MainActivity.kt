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
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
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
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.TextButton
import androidx.compose.runtime.DisposableEffect
import androidx.compose.ui.text.font.FontWeight
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.carebridge.elder.notify.showTestReminder
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.carebridge.elder.data.ApiClient
import com.carebridge.elder.data.Pairing
import com.carebridge.elder.data.RedeemBody
import com.carebridge.elder.notify.ensureReminderChannel
import com.carebridge.elder.ui.theme.CareBridgeTheme
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

        // targetSdk 35 draws edge to edge regardless; this is the call that
        // makes the system bars transparent and their icons dark, so they sit
        // on the app's own paper instead of a black strip above it.
        enableEdgeToEdge()

        setContent {
            CareBridgeTheme {
                // Read once into state rather than computed before setContent.
                // Computed outside, it was decided before the code had been
                // typed and nothing recomputed it afterwards, so a phone that
                // paired perfectly stayed on the pairing form with a line of
                // text under the button as its only sign anything had happened.
                //
                // Paired but signed out reads every reminder as "cannot reach
                // CareBridge", because the API ignores anything without a
                // token. That phone goes back to setup rather than on to a
                // screen that cannot work.
                var ready by remember {
                    mutableStateOf(Pairing.load(this) != null && ApiClient.isSignedIn())
                }

                if (ready) ReadyScreen(
                    onShowMedicine = {
                        startActivity(
                            Intent(this, ReminderActivity::class.java).putExtra(
                                ReminderActivity.EXTRA_SHOW_LIST,
                                true,
                            ),
                        )
                    },
                ) else PairingScreen(onPaired = { ready = true })
            }
        }
    }
}

/**
 * What the family sees once the phone is paired.
 *
 * Not for the elder — she is reached by the reminder itself and never opens
 * this. It exists because every permission that stops a reminder working
 * fails silently, and somebody setting the phone up deserves to be told which
 * one rather than discovering it at eight in the morning.
 */
@Composable
private fun ReadyScreen(onShowMedicine: () -> Unit) {
    val context = LocalContext.current
    var checks by remember { mutableStateOf(setupChecks(context)) }
    var testNote by remember { mutableStateOf<String?>(null) }

    // Re-read on every return from a settings screen, so a switch that was
    // just flipped shows as fixed without restarting the app.
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) checks = setupChecks(context)
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .safeDrawingPadding()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text("CareBridge is set up", fontSize = 28.sp, fontWeight = FontWeight.Bold)

        Button(
            onClick = onShowMedicine,
            modifier = Modifier.fillMaxWidth().height(72.dp).padding(top = 20.dp),
        ) {
            Text("Show my medicine", fontSize = 22.sp)
        }

        Text(
            "For the family",
            fontSize = 15.sp,
            modifier = Modifier.padding(top = 32.dp, bottom = 4.dp),
        )

        checks.forEach { check ->
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 10.dp),
            ) {
                Text(
                    (if (check.ok) "✓  " else "✕  ") + check.title,
                    fontSize = 20.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(check.why, fontSize = 15.sp, modifier = Modifier.padding(top = 2.dp))

                if (!check.ok && check.fix != null) {
                    TextButton(onClick = {
                        runCatching { context.startActivity(check.fix) }
                    }) { Text("Turn this on", fontSize = 17.sp) }
                }
            }
        }

        OutlinedButton(
            onClick = {
                testNote = "Lock the phone now. It will ring in 10 seconds."
                showTestReminder(context)
            },
            modifier = Modifier.fillMaxWidth().height(64.dp).padding(top = 16.dp),
        ) {
            Text("Test the locked screen", fontSize = 19.sp)
        }

        testNote?.let {
            Text(it, fontSize = 16.sp, modifier = Modifier.padding(top = 12.dp))
        }

        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun PairingScreen(onPaired: () -> Unit) {
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
        modifier = Modifier.fillMaxSize().safeDrawingPadding().padding(28.dp),
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

                                // The phone must also sign in AS the elder, or
                                // it can be pushed to and then cannot read the
                                // reminder it was pushed about.
                                val signedIn = reply.customToken?.let {
                                    withContext(Dispatchers.IO) { ApiClient.signIn(it) }
                                } ?: false

                                status = when {
                                    !signedIn ->
                                        "Paired, but this phone could not sign in. Ask for a new code."
                                    !reply.deviceRegistered ->
                                        "Signed in, but this phone cannot be reminded yet."
                                    else ->
                                        "Ready. This is ${reply.elderName}'s phone."
                                }

                                // Only a phone that can actually read its own
                                // reminders moves on. The other two outcomes
                                // stay here, where the sentence explaining what
                                // is still wrong is.
                                if (signedIn) onPaired()
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
