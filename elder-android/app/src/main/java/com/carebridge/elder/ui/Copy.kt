package com.carebridge.elder.ui

import java.util.Locale

/**
 * What the elder reads and hears, in the language the server says they speak.
 *
 * Deliberately not `res/values-te/`. Android resource qualifiers follow the
 * *device* locale, but the language here belongs to the person, not the
 * handset — it arrives per reminder as `elder_language`. A shared phone, or
 * Amma's own phone left in English, would otherwise show the wrong language
 * with nothing to explain why.
 *
 * The wording is taken from the web client's `frontend/src/i18n.ts` rather
 * than translated afresh, so both screens say the same thing the same way.
 */
object Copy {

    private const val TELUGU = "te"

    fun medicineTime(language: String?) =
        if (language == TELUGU) "మందు వేసుకునే సమయం" else "Medicine time"

    fun tookIt(language: String?) =
        if (language == TELUGU) "తీసుకున్నాను" else "I took it"

    fun remindLater(language: String?) =
        if (language == TELUGU) "తర్వాత గుర్తు చేయండి" else "Remind me later"

    fun listening(language: String?) =
        if (language == TELUGU) "వింటున్నాను…" else "Listening…"

    fun speakToCareBridge(language: String?) =
        if (language == TELUGU) "CareBridge తో మాట్లాడండి" else "Speak to CareBridge"

    fun recordedThanks(language: String?) =
        if (language == TELUGU) "ధన్యవాదాలు. నమోదు చేశాను." else "Thank you. I have recorded it."

    fun willRemindInTen(language: String?) =
        if (language == TELUGU) "సరే, పది నిమిషాల్లో మళ్ళీ గుర్తు చేస్తాను."
        else "Alright, I will remind you again in ten minutes."

    fun playAgain(language: String?) =
        if (language == TELUGU) "మళ్ళీ వినండి" else "Hear it again"

    fun nowPlaying(language: String?) =
        if (language == TELUGU) "వినిపిస్తోంది..." else "Playing..."

    /** Shown when the phone could not reach the server, not when nothing is due. */
    fun couldNotCheck(language: String?) =
        if (language == TELUGU) "మందు వివరాలు చూడలేకపోయాను"
        else "I could not check your medicines"

    fun couldNotCheckHint(language: String?) =
        if (language == TELUGU) "ఇంటర్నెట్ కనెక్షన్ చూడండి, మళ్ళీ ప్రయత్నించండి."
        else "Check the internet connection, then try again."

    fun tryAgain(language: String?) =
        if (language == TELUGU) "మళ్ళీ ప్రయత్నించు" else "Try again"

    fun nothingDue(language: String?) =
        if (language == TELUGU) "ప్రస్తుతం మందు ఏదీ లేదు" else "Nothing to take right now"

    /**
     * The line under "nothing to take". It was hardcoded English on the
     * handset while every other word on the screen was translated, so a Telugu
     * speaker met one sentence she could not read on the one screen that is
     * meant to need no reading. Wording matches i18n.ts `willLetYouKnow`.
     */
    fun nothingDueHint(language: String?) =
        if (language == TELUGU) "సమయం అయినప్పుడు CareBridge మీకు తెలియజేస్తుంది."
        else "CareBridge will let you know when it is time."

    /** Spoken when there is no recording, or the recording will not play. */
    fun spokenPrompt(language: String?, medicine: String) =
        if (language == TELUGU) "$medicine వేసుకోండి"
        else "It is time for your $medicine"

    /**
     * Telugu voice data is often absent on a fresh handset, and TextToSpeech
     * falls back to whatever it has. That is acceptable: the caregiver's own
     * recording is the voice that matters, and this only ever speaks when the
     * recording is missing or will not play.
     */
    fun ttsLocale(language: String?): Locale =
        if (language == TELUGU) Locale("te", "IN") else Locale("en", "IN")

    /**
     * Listen in the language she actually speaks.
     *
     * Asking for en-IN while a Telugu speaker answers does not degrade to
     * something usable — it returns confident English nonsense, which reaches
     * the agent as a reply nobody can act on and counts against her as an
     * unclear answer. The backend has always been ready for Telugu
     * (`speak_language` in the agent prompt); only the phone was not.
     */
    fun recognizerTag(language: String?): String =
        if (language == TELUGU) "te-IN" else "en-IN"
}
