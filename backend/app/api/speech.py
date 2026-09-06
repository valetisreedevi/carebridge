import logging

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api import deps
from app.api.auth import current_elder_id
from app.api.schemas import SpeakRequest
from app.config import get_settings

router = APIRouter(prefix="/api", tags=["speech"])

logger = logging.getLogger(__name__)


@router.post("/speech")
def speak(
    request: SpeakRequest,
    # Unused, and required. It is what makes this a paired phone asking rather
    # than anyone on the internet spending the project's synthesis quota.
    elder_id: str = Depends(current_elder_id),
):
    """What the screen is saying, as sound.

    Deliberately separate from /api/agent/chat. Two of the three things this
    screen says out loud - "I have recorded that" and "I will remind you in ten
    minutes" - never go near the model at all, and a chat reply that has
    already marked a dose as taken must never come back as a failure because a
    voice could not be made for it.
    """
    if not get_settings().tts_enabled:
        raise HTTPException(status_code=503, detail="Speech is switched off")

    try:
        audio = deps.speech_service().synthesise(request.text, request.language)
    except Exception as exc:
        # The screen has the words already and falls back to its own voice, so
        # this is a degradation rather than an outage. Logged, not raised past
        # the status code the client knows how to interpret.
        logger.warning("Could not synthesise %s: %s", request.language, exc)
        raise HTTPException(status_code=502, detail="Could not synthesise speech")

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=300"},
    )
