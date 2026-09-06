"""The elder's own language, spoken by a voice the phone does not have to own.

A Windows laptop carries Microsoft David, Zira and Mark, and all three of them
are en-US. Asked for Telugu, Chrome hands the sentence to one of them anyway:
it reads the Latin characters and the digits out loud and passes over the
Telugu script in silence. "ఈ Eye Drops ని రాత్రి 7:35 గంటలకు తీసుకోవాలి" arrives
as "eye drops 7:35". Nothing errors and nothing is logged, so the failure is
invisible to everyone except the one person it happens to - who is, by the
design of this whole product, the person least able to read the screen instead.

So the voice comes from Google rather than from the handset. It is the only
version of this that is true on every device.
"""

import logging
from functools import lru_cache

try:
    from google.cloud import texttospeech

    TTS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised by the deployed image only
    TTS_AVAILABLE = False

logger = logging.getLogger(__name__)

# Verified against the live voices endpoint rather than the documentation:
# every one of these languages has Standard-A, and Telugu has only Standard
# voices, so this is the tier that exists everywhere we need it.
VOICES = {
    "en": ("en-IN", "en-IN-Standard-A"),
    "te": ("te-IN", "te-IN-Standard-A"),
    "hi": ("hi-IN", "hi-IN-Standard-A"),
    "ta": ("ta-IN", "ta-IN-Standard-A"),
    "kn": ("kn-IN", "kn-IN-Standard-A"),
}

# For a language nobody has recorded a voice for yet. Wrong, and audible, which
# is the better half of the trade this entire file exists to make.
FALLBACK = VOICES["en"]

# Slower than a newsreader, for the same reason the buttons are large. This is
# the rate the browser path used, kept so the change is only in who speaks.
SPEAKING_RATE = 0.9

# Past this she has stopped waiting for an answer to what she just asked.
SYNTHESIS_TIMEOUT_SECONDS = 5.0


class SpeechService:
    def __init__(self, client=None):
        self._client = client or texttospeech.TextToSpeechClient()

    @lru_cache(maxsize=64)
    def synthesise(self, text: str, language: str) -> bytes:
        """MP3, because it is the one encoding every browser here will play.

        Cached on the instance, which is only safe because deps.speech_service
        is a process-lifetime singleton. "I have recorded that" is said after
        every single dose and is identical every time; the second one costs
        nothing and arrives with no wait at all.
        """
        language_code, voice_name = VOICES.get(language, FALLBACK)

        response = self._client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=text),
            voice=texttospeech.VoiceSelectionParams(
                language_code=language_code, name=voice_name
            ),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=SPEAKING_RATE,
            ),
            timeout=SYNTHESIS_TIMEOUT_SECONDS,
        )

        return response.audio_content
