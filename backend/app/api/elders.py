from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends

from app.api.auth import (
    current_caregiver_id,
    mint_elder_pairing_token,
    require_elder_access,
)
from app.api import deps
from app.api.schemas import (
    CreateElderRequest,
    RegisterCaregiverTokenRequest,
    RegisterDeviceRequest,
)

router = APIRouter(prefix="/api", tags=["elders"])


@router.post("/caregivers/me", status_code=200)
def upsert_me(
    caregiver_id: str = Depends(current_caregiver_id),
):
    return deps.firestore_service().upsert_caregiver(caregiver_id)


@router.post("/caregivers/me/fcm-token", status_code=204)
def register_caregiver_token(
    request: RegisterCaregiverTokenRequest,
    caregiver_id: str = Depends(current_caregiver_id),
):
    firestore = deps.firestore_service()
    firestore.upsert_caregiver(caregiver_id)
    firestore.add_caregiver_fcm_token(caregiver_id, request.fcm_token)


@router.post("/elders", status_code=201)
def create_elder(
    request: CreateElderRequest,
    caregiver_id: str = Depends(current_caregiver_id),
):
    firestore = deps.firestore_service()
    firestore.upsert_caregiver(caregiver_id)

    elder_id = firestore.create_elder(
        name=request.name,
        caregiver_id=caregiver_id,
        phone=request.phone,
        preferred_language=request.preferred_language,
        elder_timezone=request.timezone,
    )
    return {"id": elder_id, **request.model_dump()}


@router.get("/elders")
def list_elders(caregiver_id: str = Depends(current_caregiver_id)):
    return deps.firestore_service().list_elders_for_caregiver(caregiver_id)


@router.get("/elders/{elder_id}")
def get_elder(
    elder_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    return require_elder_access(elder_id, caregiver_id, deps.firestore_service())


@router.post("/elders/{elder_id}/pairing-token")
def create_pairing_token(
    elder_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Mints the credential an elder device signs in with.

    The caregiver reads this once and enters it on the elder's phone. The
    device exchanges it for an ID token carrying an elder_id claim, which is
    the only thing the elder endpoints accept once auth is on.
    """
    elder = require_elder_access(elder_id, caregiver_id, deps.firestore_service())

    return {
        "elder_id": elder_id,
        "elder_name": elder["name"],
        "pairing_token": mint_elder_pairing_token(elder_id),
    }


@router.post("/devices", status_code=201)
def register_device(
    request: RegisterDeviceRequest,
    caregiver_id: str = Depends(current_caregiver_id),
):
    firestore = deps.firestore_service()
    require_elder_access(request.elder_id, caregiver_id, firestore)

    device_id = firestore.register_device(
        elder_id=request.elder_id,
        fcm_token=request.fcm_token,
        platform=request.platform,
    )
    return {"id": device_id, "elder_id": request.elder_id}


@router.get("/elders/{elder_id}/today")
def get_today(
    elder_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """What the caregiver dashboard renders: today's plan and where it stands."""
    firestore = deps.firestore_service()
    elder = require_elder_access(elder_id, caregiver_id, firestore)

    try:
        tz = ZoneInfo(elder.get("timezone") or "UTC")
    except ZoneInfoNotFoundError:
        tz = ZoneInfo("UTC")

    local_now = datetime.now(tz)
    start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    events = deps.event_service().list_events_for_elder_on(
        elder_id, start, start + timedelta(days=1)
    )

    medications = {
        m["id"]: m for m in firestore.list_medications_for_elder(elder_id, active_only=False)
    }

    items = []
    for event in events:
        medication = medications.get(event["medication_id"], {})
        items.append({
            "event_id": event["id"],
            "medication_id": event["medication_id"],
            "medication_name": medication.get("name", "Unknown medication"),
            "dose": medication.get("dose"),
            "food_instruction": medication.get("food_instruction"),
            "photo_object_name": medication.get("photo_object_name"),
            "scheduled_at": event["scheduled_at"],
            "local_time": event["scheduled_at"].astimezone(tz).strftime("%H:%M"),
            "status": event["status"],
            "attempt": event.get("attempt", 0),
            "max_attempts": event.get("max_attempts"),
            "confirmed_at": event.get("confirmed_at"),
            "escalated_at": event.get("escalated_at"),
            "next_attempt_at": event.get("next_attempt_at"),
        })

    # Times that have not been materialised into events yet still belong on the
    # dashboard, otherwise the day looks empty until the first reminder fires.
    materialised = {(e["medication_id"], e["local_time"]) for e in items}
    for medication in firestore.list_medications_for_elder(elder_id):
        for value in medication.get("schedule_times", []):
            if (medication["id"], value) in materialised:
                continue
            items.append({
                "event_id": None,
                "medication_id": medication["id"],
                "medication_name": medication["name"],
                "dose": medication.get("dose"),
                "food_instruction": medication.get("food_instruction"),
                "photo_object_name": medication.get("photo_object_name"),
                "scheduled_at": None,
                "local_time": value,
                "status": "UPCOMING",
                "attempt": 0,
                "max_attempts": medication.get("max_attempts"),
                "confirmed_at": None,
                "escalated_at": None,
                "next_attempt_at": None,
            })

    return {
        "elder": {"id": elder["id"], "name": elder["name"], "timezone": str(tz)},
        "date": local_now.date().isoformat(),
        "items": sorted(items, key=lambda i: i["local_time"]),
    }
