package com.carebridge.elder.ui

import android.os.Bundle
import android.speech.RecognitionListener

/** RecognitionListener has nine methods; only two of them matter here. */
class SimpleRecognitionListener(
    private val onResult: (Bundle?) -> Unit,
    private val onError: (Int) -> Unit,
) : RecognitionListener {

    override fun onResults(results: Bundle?) = onResult(results)

    override fun onError(error: Int) = onError.invoke(error)

    override fun onReadyForSpeech(params: Bundle?) = Unit
    override fun onBeginningOfSpeech() = Unit
    override fun onRmsChanged(rmsdB: Float) = Unit
    override fun onBufferReceived(buffer: ByteArray?) = Unit
    override fun onEndOfSpeech() = Unit
    override fun onPartialResults(partialResults: Bundle?) = Unit
    override fun onEvent(eventType: Int, params: Bundle?) = Unit
}
