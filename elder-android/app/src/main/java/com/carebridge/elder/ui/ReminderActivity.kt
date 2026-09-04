package com.carebridge.elder.ui

import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.util.Log
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.viewModels
import androidx.activity.compose.setContent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.LaunchedEffect
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.carebridge.elder.data.ApiClient
import com.carebridge.elder.data.Pairing
import com.carebridge.elder.notify.REMINDER_NOTIFICATION_ID
import java.util.Locale

/**
 * The screen the elder actually sees. Launched by the reminder notification's
 * full-screen intent, or from the launcher icon.
 */
class ReminderActivity : ComponentActivity() {

    companion object {
        const val EXTRA_EVENT_ID = "event_id"
        const val TAG = "CareBridge"

        /** Long enough to walk to the kitchen; short enough to not sit lit. */
        private const val GIVE_UP_AFTER_MS = 3 * 60 * 1000L
    }

    private var tts: TextToSpeech? = null
    private var player: MediaPlayer? = null
    private var recognizer: SpeechRecognizer? = null
    private var playedFor: String? = null
    private var focusRequest: AudioFocusRequest? = null
    private val model: ReminderViewModel by viewModels()
    private val handler = android.os.Handler(android.os.Looper.getMainLooper())
    private var giveUp: Runnable? = null

    /** The elder's language, as the server reports it — not the handset's. */
    private var language: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // First thing, before any logging or work that could delay it. The
        // channel's tone belongs to the system and cannot be stopped any other
        // way, and until this runs it is playing over the family's recording.
        // If this activity never starts — overlay refused, full-screen intent
        // withheld — this never runs and the notification keeps ringing, which
        // is exactly the behaviour that case needs.
        dismissNotification()
        armGiveUp()

        // Proof, in the log, that the phone really was asleep and locked when
        // this took over — not that someone was watching an unlocked screen.
        val keyguard = getSystemService(android.app.KeyguardManager::class.java)
        val power = getSystemService(android.os.PowerManager::class.java)
        Log.i(
            TAG,
            "activity_created locked=${keyguard?.isKeyguardLocked} " +
                "interactive=${power?.isInteractive}",
        )

        // The reminder is useless if the screen sleeps again halfway through
        // the recording.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)

        Pairing.load(this)
        tts = TextToSpeech(this) { status ->
            if (status == TextToSpeech.SUCCESS) {
                // The spoken fallback has to survive silent mode for the same
                // reason the recording does.
                tts?.setAudioAttributes(alarmAudio)
                tts?.language = Locale("en", "IN")
                tts?.setSpeechRate(0.9f)
            }
        }

        val eventId = intent.getStringExtra(EXTRA_EVENT_ID)

        setContent {
            val state by model.state.collectAsStateWithLifecycle()
            var listening by remember { mutableStateOf(false) }

            LaunchedEffect(eventId) { model.load(eventId) }

            // The caregiver's own recording plays once per reminder. If there
            // is no recording, or it will not play, the phone still says out
            // loud what is due — silence is the one outcome we cannot ship.
            // Keyed on the ROUND, not the current dose. Keying on the dose
            // meant the recording restarted every time she answered one, so
            // three tablets played the family's voice three times over.
            LaunchedEffect(state.queue.firstOrNull()?.eventId) {
                val reminder = state.queue.firstOrNull() ?: return@LaunchedEffect
                if (playedFor == reminder.eventId) return@LaunchedEffect
                playedFor = reminder.eventId

                language = reminder.language

                val spoken = Copy.spokenPrompt(
                    reminder.language,
                    reminder.medicationName ?: "medicine",
                )
                val url = reminder.caregiverAudioUrl

                if (url == null) speak(spoken)
                else playCaregiverVoice(ApiClient.absolute(url), spoken)
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

            // Every answer buys another three minutes: a round of three
            // tablets must not be timed out because the first two took a
            // while.
            LaunchedEffect(state.index) { armGiveUp() }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        dismissNotification()

        // Was recreate(), which tore the screen down and rebuilt it — so when
        // three medicines arrived at once the last push won and the first two
        // were never seen. The queue already holds every open dose, so a
        // refetch is all a new arrival needs.
        model.load(null)
    }

    /**
     * Stands down after three minutes of no answer.
     *
     * Writes NOTHING to the server — no taken, no snooze, no decline. The
     * backend's own ladder already owns that outcome: the dose stays open, the
     * next reminder fires on schedule, and the family is told if it is never
     * answered. An auto-snooze here would inflate the snooze count the
     * escalation logic reads, so silence would quietly stop reading as silence.
     *
     * The practical half matters too: FLAG_KEEP_SCREEN_ON otherwise leaves the
     * phone lit until the battery goes, and never returns it to the lock screen
     * for the next reminder to raise.
     */
    private fun armGiveUp() {
        giveUp?.let { handler.removeCallbacks(it) }
        val task = Runnable {
            Log.i(TAG, "unanswered_standing_down")
            stopVoice()
            releaseAudioFocus()
            dismissNotification()
            finish()
        }
        giveUp = task
        handler.postDelayed(task, GIVE_UP_AFTER_MS)
    }

    private fun dismissNotification() {
        runCatching {
            NotificationManagerCompat.from(this).cancel(REMINDER_NOTIFICATION_ID)
        }
    }

    /**
     * Stops the recording, without giving up audio focus.
     *
     * Focus is deliberately kept: every caller is about to speak, and handing
     * it back only to take it again lets whatever else is playing surface in
     * the gap.
     */
    private fun stopVoice() {
        player?.let { existing ->
            runCatching { if (existing.isPlaying) existing.stop() }
            existing.release()
        }
        player = null
    }

    /**
     * The alarm stream, deliberately.
     *
     * A reminder that a dose is due is not media. On the media stream it is
     * silenced by vibrate, by Do Not Disturb, and by a volume slider an elder
     * may have nudged to zero months ago — and it fails silently every time,
     * which is the worst way for a medication reminder to fail. USAGE_ALARM is
     * the one usage Android will let through all three.
     */
    private val alarmAudio: AudioAttributes by lazy {
        AudioAttributes.Builder()
            .setUsage(AudioAttributes.USAGE_ALARM)
            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
            .build()
    }

    private fun takeAudioFocus() {
        val manager = getSystemService(AudioManager::class.java) ?: return

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val request = AudioFocusRequest
                .Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                .setAudioAttributes(alarmAudio)
                .build()
            focusRequest = request
            manager.requestAudioFocus(request)
        }
    }

    private fun releaseAudioFocus() {
        val manager = getSystemService(AudioManager::class.java) ?: return

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            focusRequest?.let { manager.abandonAudioFocusRequest(it) }
        }
        focusRequest = null
    }

    private fun playCaregiverVoice(url: String, spokenFallback: String) {
        val manager = getSystemService(AudioManager::class.java)
        val volume = manager?.getStreamVolume(AudioManager.STREAM_ALARM) ?: -1
        val max = manager?.getStreamMaxVolume(AudioManager.STREAM_ALARM) ?: -1

        // prepareAsync fails asynchronously, so the surrounding runCatching
        // cannot see it. Without an error listener a bad or expired URL is
        // total silence and the elder is simply never reminded.
        val fallBackToSpeech = {
            Log.w(TAG, "audio_failed falling back to speech")
            releaseAudioFocus()
            speak(spokenFallback)
        }

        val started = runCatching {
            player?.release()
            takeAudioFocus()

            player = MediaPlayer().apply {
                setAudioAttributes(alarmAudio)
                // Headers matter for the API-served fallback: without them it
                // is a 401 and the family's voice never plays.
                setDataSource(
                    this@ReminderActivity,
                    Uri.parse(url),
                    ApiClient.mediaHeaders(url),
                )
                setOnPreparedListener {
                    Log.i(TAG, "audio_started ms=${it.duration} vol=$volume/$max")
                    it.start()
                }
                setOnCompletionListener {
                    Log.i(TAG, "audio_completed")
                    releaseAudioFocus()
                    it.release()
                    if (player === it) player = null
                }
                setOnErrorListener { failed, what, extra ->
                    Log.w(TAG, "audio_error what=$what extra=$extra")
                    failed.release()
                    if (player === failed) player = null
                    fallBackToSpeech()
                    true
                }
                prepareAsync()
            }
        }

        if (started.isFailure) fallBackToSpeech()
    }

    private fun speak(text: String) {
        if (text.isBlank()) return

        // Both paths that reach here — the confirmation after "I took it" and
        // the agent's spoken reply — used to start on top of a recording that
        // was still playing, so the family's voice and the robot's talked over
        // each other.
        stopVoice()

        // Set per utterance: the elder's language is not known until the
        // reminder has been fetched, which is after TextToSpeech is built.
        tts?.language = Copy.ttsLocale(language)
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
                    putExtra(RecognizerIntent.EXTRA_LANGUAGE, Copy.recognizerTag(language))
                    putExtra(
                        RecognizerIntent.EXTRA_LANGUAGE_PREFERENCE,
                        Copy.recognizerTag(language),
                    )

                    // An elder does not answer at conversational speed. The
                    // default cuts her off after about two seconds of silence,
                    // which turns a slow, correct answer into a failed one.
                    putExtra(
                        RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS,
                        4000L,
                    )
                    putExtra(
                        RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS,
                        3000L,
                    )
                }
            )
        }
    }

    override fun onDestroy() {
        giveUp?.let { handler.removeCallbacks(it) }
        releaseAudioFocus()
        player?.release()
        recognizer?.destroy()
        tts?.shutdown()
        super.onDestroy()
    }
}
