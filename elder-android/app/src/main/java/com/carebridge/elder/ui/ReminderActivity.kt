package com.carebridge.elder.ui

import android.content.Intent
import android.media.MediaPlayer
import android.os.Bundle
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.LaunchedEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.carebridge.elder.data.ApiClient
import com.carebridge.elder.data.Pairing
import java.util.Locale

/**
 * The screen the elder actually sees. Launched by the reminder notification's
 * full-screen intent, or from the launcher icon.
 */
class ReminderActivity : ComponentActivity() {

    companion object {
        const val EXTRA_EVENT_ID = "event_id"
    }

    private var tts: TextToSpeech? = null
    private var player: MediaPlayer? = null
    private var recognizer: SpeechRecognizer? = null
    private var playedFor: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        Pairing.load(this)
        tts = TextToSpeech(this) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = Locale("en", "IN")
                tts?.setSpeechRate(0.9f)
            }
        }

        val eventId = intent.getStringExtra(EXTRA_EVENT_ID)

        setContent {
            val model: ReminderViewModel = viewModel()
            val state by model.state.collectAsStateWithLifecycle()
            var listening by remember { mutableStateOf(false) }

            LaunchedEffect(eventId) { model.load(eventId) }

            // The caregiver's own recording plays once per reminder.
            LaunchedEffect(state.reminder?.eventId) {
                val reminder = state.reminder ?: return@LaunchedEffect
                val url = reminder.caregiverAudioUrl ?: return@LaunchedEffect
                if (playedFor == reminder.eventId) return@LaunchedEffect

                playedFor = reminder.eventId
                playCaregiverVoice(ApiClient.absolute(url))
            }

            ReminderScreen(
                state = state,
                listening = listening,
                speechAvailable = SpeechRecognizer.isRecognitionAvailable(this),
                onMic = {
                    if (listening) {
                        recognizer?.stopListening()
                        listening = false
                    } else {
                        listening = true
                        listen(
                            onHeard = { heard ->
                                listening = false
                                model.say(heard) { reply -> speak(reply) }
                            },
                            onFailed = {
                                listening = false
                                model.notice("I did not catch that.")
                            },
                        )
                    }
                },
                onTaken = model::markTaken,
                onSnooze = { model.snooze() },
            )

            LaunchedEffect(state.finished) {
                state.finished?.let { speak(it) }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        recreate()
    }

    private fun playCaregiverVoice(url: String) {
        runCatching {
            player?.release()
            player = MediaPlayer().apply {
                setDataSource(url)
                setOnPreparedListener { start() }
                prepareAsync()
            }
        }
    }

    private fun speak(text: String) {
        if (text.isBlank()) return
        tts?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "carebridge")
    }

    private fun listen(onHeard: (String) -> Unit, onFailed: () -> Unit) {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            onFailed()
            return
        }

        recognizer?.destroy()
        recognizer = SpeechRecognizer.createSpeechRecognizer(this).apply {
            setRecognitionListener(
                SimpleRecognitionListener(
                    onResult = { results ->
                        val heard = results
                            ?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                            ?.firstOrNull()
                        if (heard.isNullOrBlank()) onFailed() else onHeard(heard)
                    },
                    onError = { onFailed() },
                )
            )
            startListening(
                Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                    putExtra(
                        RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                        RecognizerIntent.LANGUAGE_MODEL_FREE_FORM,
                    )
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE, "en-IN")
                }
            )
        }
    }

    override fun onDestroy() {
        player?.release()
        recognizer?.destroy()
        tts?.shutdown()
        super.onDestroy()
    }
}
