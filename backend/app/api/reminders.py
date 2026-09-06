from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import current_elder_id
from app.api import deps
from app.api.schemas import DeclineRequest, SnoozeRequest
from app.models.medication import FOOD_INSTRUCTION_TEXT, FoodInstruction
from app.models.medication_event import InvalidTransition

router = APIRouter(prefix="/api", tags=["reminders"])


def _event_for_elder(event_id: str, elder_id: str) -> dict:
    event = deps.event_service().get_event(event_id)

    if not event or event["elder_id"] != elder_id:
        raise HTTPException(status_code=404, detail="Reminder not found")

    return event


def _food_text(medication: dict) -> str:
    try:
        return FOOD_INSTRUCTION_TEXT[FoodInstruction(medication.get("food_instruction"))]
    except ValueError:
        return "as instructed"


def _present(event: dict, medication: dict, elder: dict | None = None) -> dict:
    """Everything the elder screen needs in one payload."""
    photo = medication.get("photo_object_name")
    audio = medication.get("caregiver_audio_object_name")
    storage = deps.storage_service()

    # Signing needs a service-account key. On user credentials it is
    # unavailable, so clients fall back to streaming through the API.
    photo_url = storage.signed_url(photo) if photo else None
    audio_url = storage.signed_url(audio) if audio else None

    return {
        "event_id": event["id"],
        "elder_id": event["elder_id"],
        # Named, because a phone can be shared. "Time for your eye drops" on a
        # side table between two people is ambiguous, and ambiguity here means
        # the wrong person takes a tablet.
        "elder_name": (elder or {}).get("name"),
        # The screen is read and spoken in the elder's own language, and a
        # shared phone can hold a queue belonging to two people who do not
        # share one. So it travels per reminder rather than per device.
        "elder_language": (elder or {}).get("preferred_language") or "en",
        "medication_id": medication["id"],
        "medication_name": medication.get("name"),
        "dose": medication.get("dose"),
        "food_instruction": medication.get("food_instruction"),
        "food_instruction_text": _food_text(medication),
        "notes": medication.get("notes"),
        "status": event["status"],
        "attempt": event.get("attempt", 0),
        "max_attempts": event.get("max_attempts"),
        "scheduled_at": event["scheduled_at"],
        # When it last actually rang, which is not the same as it being open.
        # A screen opening on a reminder that is merely still unanswered must
        # not play the family's voice at her; a screen opening because one just
        # went off should. Only this field separates the two.
        "last_attempt_at": event.get("last_attempt_at"),
        "photo_url": photo_url or (
            f"/api/reminders/{event['id']}/image" if photo else None
        ),
        "caregiver_audio_url": audio_url or (
            f"/api/reminders/{event['id']}/audio" if audio else None
        ),
        "has_photo": bool(photo),
        "has_caregiver_audio": bool(audio),
    }


@router.get("/reminders/active")
def get_active_reminder(elder_id: str = Depends(current_elder_id)):
    """What the elder device shows when it wakes up on a notification.

    A morning is rarely one tablet, so every open reminder is returned and the
    device walks them one at a time. `reminder` stays as the first of them so
    older clients keep working unchanged.
    """
    firestore = deps.firestore_service()
    elder = firestore.get_elder(elder_id)

    presented = []
    for event in deps.event_service().list_open_events_for_elder(
        elder_id, live_within=deps.reminder_service().live_window
    ):
        medication = firestore.get_medication(event["medication_id"])
        if medication and medication.get("active", True):
            presented.append(_present(event, medication, elder))

    if not presented:
        return {"active": False, "reminder": None, "reminders": [], "remaining": 0}

    return {
        "active": True,
        "reminder": presented[0],
        "reminders": presented,
        "remaining": len(presented),
    }


@router.get("/medication-events/{event_id}")
def get_event(
    event_id: str,
    elder_id: str = Depends(current_elder_id),
):
    firestore = deps.firestore_service()
    event = _event_for_elder(event_id, elder_id)
    medication = firestore.get_medication(event["medication_id"])

    if not medication:
        raise HTTPException(status_code=404, detail="Medication not found")

    return _present(event, medication, firestore.get_elder(elder_id))


def _apply(action, *args) -> dict:
    try:
        return action(*args)
    except InvalidTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/reminders/{event_id}/taken")
def mark_taken(
    event_id: str,
    elder_id: str = Depends(current_elder_id),
):
    event = _event_for_elder(event_id, elder_id)

    if event["status"] == "TAKEN":
        return {"status": "TAKEN", "message": "Already recorded as taken"}

    updated = _apply(deps.event_service().confirm_event, event_id)
    return {"status": updated["status"], "confirmed_at": updated["confirmed_at"]}


@router.post("/reminders/{event_id}/snooze")
def snooze(
    event_id: str,
    request: SnoozeRequest,
    elder_id: str = Depends(current_elder_id),
):
    _event_for_elder(event_id, elder_id)
    updated = _apply(deps.event_service().snooze_event, event_id, request.minutes)

    return {
        "status": updated["status"],
        "next_attempt_at": updated["next_attempt_at"],
        "minutes": request.minutes,
    }


@router.post("/reminders/{event_id}/decline")
def decline(
    event_id: str,
    request: DeclineRequest,
    elder_id: str = Depends(current_elder_id),
):
    event = _event_for_elder(event_id, elder_id)
    updated = _apply(deps.event_service().decline_event, event_id, request.reason)

    firestore = deps.firestore_service()
    elder = firestore.get_elder(elder_id)
    medication = firestore.get_medication(event["medication_id"])

    if elder and medication:
        deps.notification_service().notify_caregiver(
            elder,
            medication,
            event,
            reason="DECLINED",
            message=f"{elder['name']} declined the {medication['name']}.",
        )

    return {"status": updated["status"], "declined_at": updated["declined_at"]}


def _stream_media(event_id: str, elder_id: str, field: str, missing: str):
    from fastapi import Response

    event = _event_for_elder(event_id, elder_id)
    medication = deps.firestore_service().get_medication(event["medication_id"])
    object_name = (medication or {}).get(field)

    if not object_name:
        raise HTTPException(status_code=404, detail=missing)

    content, content_type = deps.storage_service().read(object_name)
    return Response(
        content=content,
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/reminders/{event_id}/image")
def reminder_image(event_id: str, elder_id: str = Depends(current_elder_id)):
    return _stream_media(event_id, elder_id, "photo_object_name", "No photo uploaded")


@router.get("/reminders/{event_id}/audio")
def reminder_audio(event_id: str, elder_id: str = Depends(current_elder_id)):
    return _stream_media(
        event_id,
        elder_id,
        "caregiver_audio_object_name",
        "No voice recording uploaded",
    )
