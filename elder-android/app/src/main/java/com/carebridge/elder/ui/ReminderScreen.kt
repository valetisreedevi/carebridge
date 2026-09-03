package com.carebridge.elder.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
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
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.carebridge.elder.data.ApiClient

// A warm palette rather than a clinical one. This screen appears beside
// someone's bed at ten at night; it should not look like a hospital form.
private val Paper = Color(0xFFFBF8F3)
private val Card = Color(0xFFFFFFFF)
private val Ink = Color(0xFF17212B)
private val Muted = Color(0xFF6B7A88)
private val Green = Color(0xFF1B7A4B)
private val GreenWash = Color(0xFFE8F3EC)
private val Line = Color(0xFFE7E0D6)
private val Amber = Color(0xFF9A5B14)

/**
 * What the elder sees when a dose is due.
 *
 * Designed for one pair of eyes that may not be sharp, one hand that may not
 * be steady, and no interest whatsoever in learning an interface: very large
 * type, one thing per line, and two targets big enough to hit without aiming.
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
    val language = state.reminder?.language

    if (state.loading) {
        Box(
            modifier = Modifier.fillMaxSize().background(Paper),
            contentAlignment = Alignment.Center,
        ) { CircularProgressIndicator(color = Green) }
        return
    }

    val reminder = state.reminder

    if (reminder == null) {
        Column(
            modifier = Modifier.fillMaxSize().background(Paper).padding(36.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                Copy.nothingDue(language),
                fontSize = 34.sp,
                fontWeight = FontWeight.SemiBold,
                color = Ink,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(16.dp))
            Text(
                state.notice ?: "CareBridge will let you know when it is time.",
                fontSize = 21.sp,
                color = Muted,
                textAlign = TextAlign.Center,
            )
        }
        return
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Paper)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            Copy.medicineTime(language).uppercase(),
            fontSize = 16.sp,
            fontWeight = FontWeight.Bold,
            color = Green,
        )

        Spacer(Modifier.height(24.dp))

        MedicinePicture(
            url = reminder.photoUrl,
            fallbackLetter = reminder.medicationName?.trim()?.firstOrNull()?.uppercase(),
        )

        Spacer(Modifier.height(28.dp))

        Text(
            reminder.medicationName ?: "Your medicine",
            fontSize = 44.sp,
            fontWeight = FontWeight.Bold,
            color = Ink,
            textAlign = TextAlign.Center,
            lineHeight = 50.sp,
        )

        reminder.dose?.takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(14.dp))
            Chip(text = it)
        }

        reminder.foodInstruction?.takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(14.dp))
            Text(
                it,
                fontSize = 23.sp,
                color = Muted,
                textAlign = TextAlign.Center,
            )
        }

        reminder.notes?.takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(10.dp))
            Text(it, fontSize = 20.sp, color = Muted, textAlign = TextAlign.Center)
        }

        state.turns.takeLast(3).forEach { turn ->
            Spacer(Modifier.height(14.dp))
            Text(
                turn.text,
                fontSize = 21.sp,
                color = if (turn.fromElder) Ink else Green,
                textAlign = TextAlign.Center,
            )
        }

        state.notice?.let {
            Spacer(Modifier.height(18.dp))
            Text(it, fontSize = 20.sp, color = Amber, textAlign = TextAlign.Center)
        }

        Spacer(Modifier.height(36.dp))

        // The confirming action is the largest thing on the screen and the
        // only filled one. Nothing else should compete with it.
        Button(
            onClick = onTaken,
            enabled = !state.busy,
            shape = RoundedCornerShape(20.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Green),
            modifier = Modifier.fillMaxWidth().height(96.dp),
        ) {
            Text(
                Copy.tookIt(language),
                fontSize = 30.sp,
                fontWeight = FontWeight.SemiBold,
                color = Color.White,
            )
        }

        Spacer(Modifier.height(14.dp))

        OutlinedButton(
            onClick = onSnooze,
            enabled = !state.busy,
            shape = RoundedCornerShape(20.dp),
            modifier = Modifier.fillMaxWidth().height(78.dp),
        ) {
            Text(Copy.remindLater(language), fontSize = 24.sp, color = Ink)
        }

        if (speechAvailable) {
            Spacer(Modifier.height(8.dp))
            TextButton(onClick = onMic, enabled = !state.busy) {
                Text(
                    if (listening) Copy.listening(language)
                    else Copy.speakToCareBridge(language),
                    fontSize = 20.sp,
                    color = if (listening) Green else Muted,
                )
            }
        }

        Spacer(Modifier.height(24.dp))
    }
}

/**
 * The photo the family took of the actual tablet.
 *
 * It is the thing an elder recognises fastest — faster than the name, which
 * may be in an alphabet they do not read. When there is no photo, a large
 * initial keeps the layout from collapsing into something that looks broken.
 */
@Composable
private fun MedicinePicture(url: String?, fallbackLetter: String?) {
    val shape = RoundedCornerShape(28.dp)
    val frame = Modifier
        .size(248.dp)
        .clip(shape)
        .border(2.dp, Line, shape)

    if (url != null) {
        AsyncImage(
            model = ApiClient.absolute(url),
            contentDescription = null,
            contentScale = ContentScale.Crop,
            modifier = frame.background(Card),
        )
        return
    }

    Box(
        modifier = frame.background(GreenWash),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            fallbackLetter ?: "?",
            fontSize = 88.sp,
            fontWeight = FontWeight.Bold,
            color = Green,
        )
    }
}

/** The dose, set apart so it reads as a quantity rather than more prose. */
@Composable
private fun Chip(text: String) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(16.dp))
            .background(GreenWash)
            .padding(horizontal = 22.dp, vertical = 10.dp),
    ) {
        Text(text, fontSize = 27.sp, fontWeight = FontWeight.SemiBold, color = Green)
    }
}
