package com.carebridge.elder.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
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
import com.carebridge.elder.data.RegisterDeviceBody
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
    var elderId by remember { mutableStateOf("") }
    var status by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    val askNotifications = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { }

    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(
                context, Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED

            if (!granted) askNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
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
            value = elderId,
            onValueChange = { elderId = it.trim() },
            label = { Text("Code") },
            modifier = Modifier.fillMaxWidth(),
        )

        Button(
            onClick = {
                Pairing.save(context, elderId)
                status = "Pairing…"

                FirebaseMessaging.getInstance().token
                    .addOnSuccessListener { token ->
                        scope.launch {
                            val registered = withContext(Dispatchers.IO) {
                                runCatching {
                                    ApiClient.api.registerDevice(
                                        RegisterDeviceBody(elderId, token)
                                    )
                                }
                            }
                            status = if (registered.isSuccess) {
                                "Ready. Reminders will arrive here."
                            } else {
                                "Could not reach CareBridge. Check the code."
                            }
                        }
                    }
                    .addOnFailureListener {
                        status = "This phone cannot receive reminders yet."
                    }
            },
            enabled = elderId.length > 4,
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
    }
}
