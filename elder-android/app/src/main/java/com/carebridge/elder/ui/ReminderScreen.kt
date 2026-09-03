package com.carebridge.elder.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.carebridge.elder.data.ApiClient

private val Green = Color(0xFF1F7A4D)
private val Ink = Color(0xFF17212B)
private val Muted = Color(0xFF61717F)

/**
 * Deliberately plain: very large type, three tall targets, no navigation.
 */
@Composable
fun ReminderScreen(
    state: ReminderUiState,
    listening: Boolean,
    speechAvailable: Boolean,
    onMic: () -> Unit,
    onTaken: () -> Unit,
    onSnooze: () -> Unit,
) {
    // Whose language, not the handset's. See Copy.
    val language = state.reminder?.language
    if (state.loading) {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) { CircularProgressIndicator() }
        return
    }

    val reminder = state.reminder

    if (reminder == null) {
        Column(
            modifier = Modifier.fillMaxSize().padding(32.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(Copy.nothingDue(language), fontSize = 30.sp, color = Ink)
            Text(
                state.notice ?: "CareBridge will let you know when it is time.",
                fontSize = 20.sp,
                color = Muted,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 12.dp),
            )
        }
        return
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            Copy.medicineTime(language),
            fontSize = 34.sp,
            fontWeight = FontWeight.Bold,
            color = Ink,
        )

        reminder.photoUrl?.let { url ->
            AsyncImage(
                model = ApiClient.absolute(url),
                contentDescription = null,
                contentScale = ContentScale.Crop,
                modifier = Modifier
                    .padding(top = 24.dp)
                    .size(220.dp),
            )
        }

        Text(
            reminder.medicationName ?: "Your medicine",
            fontSize = 40.sp,
            fontWeight = FontWeight.Bold,
            color = Ink,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(top = 24.dp),
        )

        reminder.dose?.let { Text(it, fontSize = 30.sp, color = Ink) }

        reminder.foodInstruction?.let {
            Text(
                "Take it $it",
                fontSize = 24.sp,
                color = Muted,
                modifier = Modifier.padding(top = 8.dp),
            )
        }

        state.turns.takeLast(4).forEach { turn ->
            Text(
                turn.text,
                fontSize = 21.sp,
                color = if (turn.fromElder) Ink else Green,
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 12.dp),
            )
        }

        state.notice?.let {
            Text(
                it,
                fontSize = 20.sp,
                color = Color(0xFFA9601A),
                textAlign = TextAlign.Center,
                modifier = Modifier.padding(top = 16.dp),
            )
        }

        if (speechAvailable) {
            OutlinedButton(
                onClick = onMic,
                enabled = !state.busy,
                shape = RoundedCornerShape(16.dp),
                modifier = Modifier
                    .fillMaxWidth()
                    .height(76.dp)
                    .padding(top = 28.dp),
            ) {
                Text(
                    if (listening) Copy.listening(language) else Copy.speakToCareBridge(language),
                    fontSize = 24.sp,
                )
            }
        }

        Button(
            onClick = onTaken,
            enabled = !state.busy,
            shape = RoundedCornerShape(16.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Green),
            modifier = Modifier
                .fillMaxWidth()
                .height(84.dp)
                .padding(top = 16.dp),
        ) {
            Text(Copy.tookIt(language), fontSize = 28.sp, color = Color.White)
        }

        OutlinedButton(
            onClick = onSnooze,
            enabled = !state.busy,
            shape = RoundedCornerShape(16.dp),
            modifier = Modifier
                .fillMaxWidth()
                .height(84.dp)
                .padding(top = 12.dp),
        ) {
            Text(Copy.remindLater(language), fontSize = 26.sp, color = Ink)
        }

        Text(
            "",
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(bottom = 24.dp),
        )
    }
}
