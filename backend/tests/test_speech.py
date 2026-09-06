"""The screen's words, said out loud in the language they were written in.

The bug these guard against is silent by construction: a handset with no Telugu
voice speaks the Latin characters and the digits, skips the script, and reports
nothing wrong. Only the voice actually requested tells you it worked.
"""

import pytest

from app.api import deps
from app.services.speech_service import SpeechService


class FakeVoice:
    """Records the voice it was asked for, which is the whole assertion."""

    def __init__(self):
        self.calls = []

    def synthesize_speech(self, *, input, voice, audio_config, timeout=None):
        self.calls.append(voice.name)
        return type("Response", (), {"audio_content": b"ID3 pretend-mp3"})()


@pytest.fixture
def voice(monkeypatch):
    fake = FakeVoice()
    # One instance, handed back every time, because deps.speech_service is
    # lru_cached in the running app. Building a fresh one per request would
    # quietly defeat the synthesis cache and pass anyway.
    service = SpeechService(client=fake)
    monkeypatch.setattr(deps, "speech_service", lambda: service)
    return fake


def test_a_paired_phone_gets_her_words_back_as_sound(client, voice):
    response = client.post(
        "/api/speech",
        json={"text": "మందు వేసుకోండి", "language": "te"},
        headers={"X-Elder-Id": "elder_1"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content


def test_a_phone_with_no_credential_is_not_a_synthesis_budget(client, voice):
    anonymous = client.post("/api/speech", json={"text": "hello", "language": "en"})

    assert anonymous.status_code == 401
    assert voice.calls == []


def test_telugu_is_spoken_by_a_telugu_voice(client, voice):
    """The regression test for the actual bug.

    An English voice handed Telugu does not fail - it reads the digits and goes
    quiet for the rest, which is why this asserts on the voice requested rather
    than on the response being 200.
    """
    client.post(
        "/api/speech",
        json={"text": "ఈ Eye Drops ని రాత్రి 7:35 గంటలకు తీసుకోవాలి.", "language": "te"},
        headers={"X-Elder-Id": "elder_1"},
    )

    assert voice.calls == ["te-IN-Standard-A"]


def test_a_language_nobody_has_recorded_still_speaks(client, voice):
    response = client.post(
        "/api/speech",
        json={"text": "something", "language": "xx"},
        headers={"X-Elder-Id": "elder_1"},
    )

    assert response.status_code == 200
    assert voice.calls == ["en-IN-Standard-A"]


def test_the_same_sentence_is_only_ever_bought_once(client, voice):
    for _ in range(2):
        client.post(
            "/api/speech",
            json={"text": "నమోదు చేశాను", "language": "te"},
            headers={"X-Elder-Id": "elder_1"},
        )

    assert len(voice.calls) == 1


def test_speech_switched_off_is_a_refusal_the_screen_can_act_on(
    client, voice, monkeypatch
):
    """503 rather than a hang, so the browser falls back to its own voice."""
    from app.api import speech as speech_module

    settings = speech_module.get_settings()
    monkeypatch.setattr(settings, "tts_enabled", False)

    response = client.post(
        "/api/speech",
        json={"text": "anything", "language": "te"},
        headers={"X-Elder-Id": "elder_1"},
    )

    assert response.status_code == 503
    assert voice.calls == []
