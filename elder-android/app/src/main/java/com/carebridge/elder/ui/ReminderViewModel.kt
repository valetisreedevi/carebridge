package com.carebridge.elder.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.carebridge.elder.data.ApiClient
import com.carebridge.elder.data.ChatBody
import com.carebridge.elder.data.DeclineBody
import com.carebridge.elder.data.MyDay
import com.carebridge.elder.data.Reminder
import com.carebridge.elder.data.SnoozeBody
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

data class Turn(val fromElder: Boolean, val text: String)

data class ReminderUiState(
    val loading: Boolean = true,
    /** Every dose open right now, not just the first. */
    val queue: List<Reminder> = emptyList(),
    /** Which of them she is looking at. */
    val index: Int = 0,
    val turns: List<Turn> = emptyList(),
    val busy: Boolean = false,
    val notice: String? = null,
    /**
     * The fetch failed, as opposed to succeeding and finding nothing.
     *
     * Without this the two are indistinguishable on screen — an elder who
     * could not be reached and an elder with nothing due saw the same words,
     * and so did the person debugging it.
     */
    val failed: Boolean = false,
    /** Set once the LAST dose in the round is answered, not the first. */
    val finished: String? = null,
    /**
     * The rest of today, for the quiet screen.
     *
     * Kept apart from the queue on purpose: a day that will not load must
     * never be the reason a dose goes unasked, so its failure leaves this null
     * and changes nothing else.
     */
    val day: MyDay? = null,
) {
    /**
     * Derived rather than stored, so there is no second copy to fall out of
     * step with the queue — and so every existing `state.reminder` read in the
     * screen keeps working untouched.
     */
    val reminder: Reminder? get() = queue.getOrNull(index)

    /** "1 of 3", for a woman who would otherwise stop after the first tablet. */
    val position: Int get() = index + 1
    val total: Int get() = queue.size
}

class ReminderViewModel : ViewModel() {

    private val _state = MutableStateFlow(ReminderUiState())
    val state: StateFlow<ReminderUiState> = _state.asStateFlow()

    /** Remembered so the retry button does not need it passed back in. */
    private var lastEventId: String? = null

    fun retry() = load(lastEventId)

    /**
     * Today's plan, fetched alongside the queue and allowed to fail quietly.
     *
     * Opening the app off-schedule used to say only "Nothing to take right
     * now". Somebody who cannot remember whether they took the morning tablet
     * is exactly who this product is for, and their own phone could not say.
     */
    fun loadDay() {
        viewModelScope.launch {
            runCatching { ApiClient.api.myToday() }
                .onSuccess { day -> _state.update { it.copy(day = day) } }
            // On failure the screen simply stays as it was. This is context,
            // not the reminder.
        }
    }

    fun load(eventId: String?) {
        lastEventId = eventId
        loadDay()

        viewModelScope.launch {
            _state.update { it.copy(loading = true, notice = null, failed = false) }

            // Always fetch the whole round. A specific event id decides where
            // in it she starts, not whether the rest exists.
            suspend fun fetch() = ApiClient.api.activeReminder().let { active ->
                if (active.reminders.isNotEmpty()) active.reminders
                // An older API build sends only the singular field.
                else listOfNotNull(active.reminder)
            }

            // This runs the instant a sleeping phone is woken by a push, which
            // is frequently before its radio has reconnected. One attempt was
            // enough to lose the whole reminder: the fetch failed, the screen
            // said there was nothing due, and a dose that WAS due went unseen.
            var result = runCatching { fetch() }
            for (waitMs in listOf(1_500L, 4_000L)) {
                if (result.isSuccess) break
                delay(waitMs)
                result = runCatching { fetch() }
            }

            _state.update {
                result.fold(
                    onSuccess = { queue ->
                        val start = eventId
                            ?.let { wanted -> queue.indexOfFirst { r -> r.eventId == wanted } }
                            ?.coerceAtLeast(0)
                            ?: 0
                        it.copy(loading = false, queue = queue, index = start)
                    },
                    onFailure = { _ ->
                        it.copy(
                            loading = false,
                            failed = true,
                            notice = "Cannot reach CareBridge right now.",
                        )
                    },
                )
            }
        }
    }

    fun markTaken() = act { eventId ->
        ApiClient.api.markTaken(eventId)
        Copy.recordedThanks(state.value.reminder?.language)
    }

    fun snooze(minutes: Int = 10) = act { eventId ->
        ApiClient.api.snooze(eventId, SnoozeBody(minutes))
        Copy.willRemindInTen(state.value.reminder?.language)
    }

    fun decline(reason: String) = act { eventId ->
        ApiClient.api.decline(eventId, DeclineBody(reason))
        "I have let your family know."
    }

    private fun act(block: suspend (String) -> String) {
        val eventId = _state.value.reminder?.eventId ?: return
        if (_state.value.busy) return

        viewModelScope.launch {
            _state.update { it.copy(busy = true, notice = null) }

            runCatching { block(eventId) }.fold(
                onSuccess = { spoken ->
                    _state.update {
                        // Answering one dose moves to the next rather than
                        // ending the screen. Only the last one finishes it —
                        // which is the whole bug: she used to take one tablet,
                        // be told she was done, and leave two unanswered.
                        val next = it.index + 1
                        if (next < it.queue.size) {
                            it.copy(
                                busy = false,
                                index = next,
                                turns = it.turns + Turn(false, spoken),
                            )
                        } else {
                            it.copy(
                                busy = false,
                                finished = spoken,
                                turns = it.turns + Turn(false, spoken),
                            )
                        }
                    }
                },
                onFailure = {
                    _state.update {
                        it.copy(busy = false, notice = "That did not go through.")
                    }
                },
            )
        }
    }

    /** One conversational turn. The reply is spoken by the caller. */
    fun say(message: String, onReply: (String) -> Unit) {
        val reminder = _state.value.reminder ?: return
        val elderId = ApiClient.elderId ?: return
        if (_state.value.busy) return

        _state.update {
            it.copy(busy = true, notice = null, turns = it.turns + Turn(true, message))
        }

        viewModelScope.launch {
            runCatching {
                ApiClient.api.chat(ChatBody(elderId, reminder.eventId, message))
            }.fold(
                onSuccess = { reply ->
                    onReply(reply.reply)
                    _state.update {
                        it.copy(
                            busy = false,
                            turns = it.turns + Turn(false, reply.reply),
                        )
                    }
                    // The backend, not the model, is the source of truth for
                    // what actually happened.
                    load(reminder.eventId)
                },
                onFailure = {
                    _state.update {
                        it.copy(
                            busy = false,
                            notice = "I did not catch that. Please use the buttons.",
                        )
                    }
                },
            )
        }
    }

    fun notice(message: String?) {
        _state.update { it.copy(notice = message) }
    }
}
