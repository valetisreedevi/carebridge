package com.carebridge.elder.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil.compose.AsyncImage
import com.carebridge.elder.data.ApiClient
import com.carebridge.elder.data.MyDayItem
import com.carebridge.elder.ui.theme.Brand
import com.carebridge.elder.ui.theme.BrandSoft
import com.carebridge.elder.ui.theme.Card
import com.carebridge.elder.ui.theme.Ink
import com.carebridge.elder.ui.theme.Line
import com.carebridge.elder.ui.theme.LineStrong
import com.carebridge.elder.ui.theme.Muted
import com.carebridge.elder.ui.theme.Paper
import com.carebridge.elder.ui.theme.Warn

// Colour lives in ui/theme/Color.kt, shared with the theme so this screen and
// every Material control the app has not hand-coloured agree. It used to be a
// private block here, which is how the app came to hold three different greens.

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
    onRetry: () -> Unit = {},
    playing: Boolean = false,
    onPlayAgain: () -> Unit = {},
) {
    val language = state.reminder?.language

    if (state.loading) {
        Box(
            modifier = Modifier.fillMaxSize().background(Paper),
            contentAlignment = Alignment.Center,
        ) { CircularProgressIndicator(color = Brand) }
        return
    }

    val reminder = state.reminder

    // A phone that could not be reached is not a phone with nothing to do.
    // These used to render identically, which meant a failed wake looked to
    // her exactly like a quiet evening — and the dose went unanswered.
    if (state.failed) {
        Column(
            modifier = Modifier.fillMaxSize().background(Paper)
                .safeDrawingPadding().padding(36.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                Copy.couldNotCheck(language),
                fontSize = 30.sp,
                fontWeight = FontWeight.SemiBold,
                color = Ink,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(14.dp))
            Text(
                Copy.couldNotCheckHint(language),
                fontSize = 20.sp,
                color = Muted,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(32.dp))
            Button(
                onClick = onRetry,
                modifier = Modifier.fillMaxWidth().height(76.dp),
                shape = RoundedCornerShape(18.dp),
                colors = ButtonDefaults.buttonColors(containerColor = Brand),
            ) {
                Text(
                    Copy.tryAgain(language),
                    fontSize = 26.sp,
                    fontWeight = FontWeight.Bold,
                    color = Paper,
                )
            }
        }
        return
    }

    if (reminder == null) {
        // The day is fetched with the queue and is allowed to be absent; the
        // language then comes from it rather than from a reminder there is
        // none of.
        val dayLanguage = state.day?.language ?: language
        val doses = state.day?.items.orEmpty().filter { it.state != "cancelled" }

        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(Paper)
                .safeDrawingPadding()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 20.dp, vertical = 36.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                Copy.nothingDue(dayLanguage),
                fontSize = 34.sp,
                fontWeight = FontWeight.SemiBold,
                color = Ink,
                textAlign = TextAlign.Center,
            )
            Spacer(Modifier.height(16.dp))
            Text(
                state.notice ?: Copy.nothingDueHint(dayLanguage),
                fontSize = 21.sp,
                color = Muted,
                textAlign = TextAlign.Center,
            )

            // Opening the app off-schedule used to end here, on a sentence
            // that is also what a failed reminder says. Somebody who cannot
            // remember whether they took the morning tablet is exactly who
            // this product is for.
            if (doses.isNotEmpty()) {
                Spacer(Modifier.height(36.dp))
                Text(
                    Copy.todaysMedicines(dayLanguage),
                    fontSize = 26.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = Ink,
                )
                Spacer(Modifier.height(16.dp))
                doses.forEach { dose ->
                    DayRow(dose = dose, language = dayLanguage)
                    Spacer(Modifier.height(10.dp))
                }
            }
        }
        return
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Paper)
            // The paper runs under the status and navigation bars; only the
            // words are inset. targetSdk 35 lays every activity out edge to
            // edge with no way to opt out, and this screen had a fixed 32.dp
            // top padding written when the system reserved that space itself.
            .safeDrawingPadding()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Text(
            Copy.medicineTime(language).uppercase(),
            fontSize = 16.sp,
            fontWeight = FontWeight.Bold,
            color = Brand,
        )

        // Without this she takes the first tablet, sees the screen change, and
        // puts the phone down — which is exactly how two doses used to go
        // unanswered and escalate to her family. Only shown when there is in
        // fact more than one; a single dose should not be made to look like a
        // list of chores.
        if (state.total > 1) {
            Spacer(Modifier.height(8.dp))
            Text(
                "${state.position} of ${state.total}",
                fontSize = 20.sp,
                fontWeight = FontWeight.SemiBold,
                color = Ink.copy(alpha = 0.65f),
            )
        }

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
                color = if (turn.fromElder) Ink else Brand,
                textAlign = TextAlign.Center,
            )
        }

        state.notice?.let {
            Spacer(Modifier.height(18.dp))
            Text(it, fontSize = 20.sp, color = Warn, textAlign = TextAlign.Center)
        }

        // Only when there is a recording to hear. A dose with no voice should
        // not offer a button that does nothing.
        if (reminder.hasCaregiverAudio || reminder.caregiverAudioUrl != null) {
            Spacer(Modifier.height(24.dp))
            TextButton(onClick = onPlayAgain, enabled = !playing) {
                Text(
                    if (playing) Copy.nowPlaying(language) else Copy.playAgain(language),
                    fontSize = 24.sp,
                    fontWeight = FontWeight.SemiBold,
                    color = if (playing) Muted else Brand,
                )
            }
        }

        Spacer(Modifier.height(36.dp))

        // The confirming action is the largest thing on the screen and the
        // only filled one. Nothing else should compete with it.
        Button(
            onClick = onTaken,
            enabled = !state.busy,
            shape = RoundedCornerShape(20.dp),
            colors = ButtonDefaults.buttonColors(containerColor = Brand),
            modifier = Modifier.fillMaxWidth().height(96.dp),
        ) {
            Text(
                Copy.tookIt(language),
                fontSize = 30.sp,
                fontWeight = FontWeight.SemiBold,
                color = Paper,
            )
        }

        Spacer(Modifier.height(14.dp))

        // Material's default outline and label are the stock purple, which
        // is the one colour on this screen that belongs to no product. Set at
        // the call site rather than by a theme so the fix cannot be undone by
        // a later theming change, and so the disabled state stays legible
        // instead of fading to an unreadable tint of it.
        OutlinedButton(
            onClick = onSnooze,
            enabled = !state.busy,
            shape = RoundedCornerShape(20.dp),
            border = BorderStroke(2.dp, LineStrong),
            colors = ButtonDefaults.outlinedButtonColors(
                contentColor = Ink,
                disabledContentColor = Muted,
            ),
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
                    color = if (listening) Brand else Muted,
                )
            }
        }

        Spacer(Modifier.height(24.dp))
    }
}

/**
 * One dose of today, on the screen she sees when nothing is due.
 *
 * The photograph leads, because it is what she recognises fastest — the name
 * can be in an alphabet she was never taught, and the picture is the whole
 * reason the app asks the family for one. A taken dose keeps its tick: the
 * picture says WHICH medicine, not whether she has had it, and collapsing
 * those two would be worse than showing no picture at all.
 */
@Composable
private fun DayRow(dose: MyDayItem, language: String?) {
    val taken = dose.state == "taken"
    val shape = RoundedCornerShape(18.dp)

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(shape)
            .background(if (taken) BrandSoft else Card)
            .border(1.dp, if (taken) BrandSoft else Line, shape)
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(56.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(Paper),
            contentAlignment = Alignment.Center,
        ) {
            if (dose.hasPhoto) {
                AsyncImage(
                    model = ApiClient.absolute("/api/my/medications/${dose.medicationId}/image"),
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize(),
                )
            } else {
                Text(
                    if (taken) "✓" else "○",
                    fontSize = 24.sp,
                    color = if (taken) Brand else Muted,
                )
            }
        }

        Spacer(Modifier.width(14.dp))

        Column(modifier = Modifier.weight(1f)) {
            Text(
                dose.localTime,
                fontSize = 20.sp,
                fontWeight = FontWeight.SemiBold,
                color = Ink,
            )
            Text(
                dose.medicationName ?: "",
                fontSize = 24.sp,
                fontWeight = FontWeight.SemiBold,
                color = Ink,
            )
            val detail = listOfNotNull(
                dose.dose?.takeIf { it.isNotBlank() },
                dose.foodInstruction?.takeIf { it.isNotBlank() },
            ).joinToString(" · ")
            if (detail.isNotBlank()) {
                Text(detail, fontSize = 18.sp, color = Muted)
            }
        }

        Spacer(Modifier.width(10.dp))

        // The word as well as the colour. A tick and a circle at arm's length
        // in a lit room are not reliably different things.
        Text(
            when (dose.state) {
                "taken" -> Copy.doseTaken(language)
                "now" -> Copy.doseNow(language)
                "missed" -> Copy.doseMissed(language)
                else -> Copy.doseLater(language)
            },
            fontSize = 17.sp,
            fontWeight = if (taken) FontWeight.SemiBold else FontWeight.Normal,
            color = if (taken) Brand else Muted,
        )
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
        modifier = frame.background(BrandSoft),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            fallbackLetter ?: "?",
            fontSize = 88.sp,
            fontWeight = FontWeight.Bold,
            color = Brand,
        )
    }
}

/** The dose, set apart so it reads as a quantity rather than more prose. */
@Composable
private fun Chip(text: String) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(16.dp))
            .background(BrandSoft)
            .padding(horizontal = 22.dp, vertical = 10.dp),
    ) {
        Text(text, fontSize = 27.sp, fontWeight = FontWeight.SemiBold, color = Brand)
    }
}
