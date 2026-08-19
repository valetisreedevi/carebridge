package com.carebridge.elder.ui

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.carebridge.elder.data.ApiClient
import com.carebridge.elder.data.ChatBody
import com.carebridge.elder.data.DeclineBody
import com.carebridge.elder.data.Reminder
import com.carebridge.elder.data.SnoozeBody
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class Turn(val fromElder: Boolean, val text: String)

data class ReminderUiState(
    val loading: Boolean = true,
    val reminder: Reminder? = null,
    val turns: List<Turn> = emptyList(),
    val busy: Boolean = false,
    val notice: String? = null,
    /** Set once the reminder reaches a state the elder cannot act on again. */
    val finished: String? = null,
)

class ReminderViewModel : ViewModel() {

    private val _state = MutableStateFlow(ReminderUiState())
    val state: StateFlow<ReminderUiState> = _state.asStateFlow()

    fun load(eventId: String?) {
        viewModelScope.launch {
            _state.update { it.copy(loading = true, notice = null) }

            val result = runCatching {
                if (eventId != null) ApiClient.api.event(eventId)
                else ApiClient.api.activeReminder().reminder
            }

            _state.update {
                result.fold(
                    onSuccess = { reminder ->
                        it.copy(loading = false, reminder = reminder)
                    },
                    onFailure = { _ ->
                        it.copy(
                            loading = false,
                            notice = "Cannot reach CareBridge right now.",
                        )
                    },
                )
            }
        }
    }

    fun markTaken() = act { eventId ->
        ApiClient.api.markTaken(eventId)
        "Thank you. I have recorded it."
    }

    fun snooze(minutes: Int = 10) = act { eventId ->
        ApiClient.api.snooze(eventId, SnoozeBody(minutes))
        "Alright, I will remind you again in $minutes minutes."
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
                        it.copy(
                            busy = false,
                            finished = spoken,
                            turns = it.turns + Turn(false, spoken),
                        )
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
