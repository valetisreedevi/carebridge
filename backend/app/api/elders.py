from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.models.adherence import build_ledger
from app.services.adherence_service import plain_weekly_note

from app.api.auth import (
    CAREGIVER_EMAILS,
    current_caregiver_id,
    current_elder_id,
    mint_elder_pairing_token,
    require_elder_access,
    revoke_elder_sessions,
)
from app.api import deps
from app.services import course
from app.api.schemas import (
    CreateElderRequest,
    RegisterCaregiverTokenRequest,
    RegisterDeviceRequest,
    RegisterMyDeviceRequest,
    UpdateElderRequest,
)

router = APIRouter(prefix="/api", tags=["elders"])

# How long a scheduled time is given to become an event before the dashboard
# calls it missed. Covers the once-a-minute worker plus a little slack.
MISSED_GRACE = timedelta(minutes=2)


def _elder_zone(elder: dict) -> ZoneInfo:
    try:
        return ZoneInfo(elder.get("timezone") or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


@router.post("/caregivers/me", status_code=200)
def upsert_me(
    caregiver_id: str = Depends(current_caregiver_id),
):
    return deps.firestore_service().upsert_caregiver(
        caregiver_id, email=CAREGIVER_EMAILS.get(caregiver_id)
    )


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


@router.patch("/elders/{elder_id}")
def update_elder(
    elder_id: str,
    request: UpdateElderRequest,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Changes an elder's details — most usefully the timezone.

    The timezone is captured from the caregiver's browser when the elder is
    created, which is wrong whenever the two live in different places.
    """
    firestore = deps.firestore_service()
    require_elder_access(elder_id, caregiver_id, firestore)

    updates = request.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    firestore.update_elder(elder_id, updates)
    return firestore.get_elder(elder_id)


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



@router.post("/devices/mine", status_code=201)
def register_my_device(
    request: RegisterMyDeviceRequest,
    elder_id: str = Depends(current_elder_id),
):
    """A phone putting its own notification address on file.

    POST /devices needs caregiver credentials, which an elder's phone does not
    have and should not be given — so before this, a paired device could not
    register itself and no push could ever reach it. The elder id comes from
    the device's own token, never the body, so a phone can only ever sign
    itself up for the person it was paired to.
    """
    device_id = deps.firestore_service().register_device(
        elder_id=elder_id,
        fcm_token=request.fcm_token,
        platform=request.platform,
        label=request.label,
    )
    return {"id": device_id, "elder_id": elder_id}


@router.get("/elders/{elder_id}/devices")
def list_devices(
    elder_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Which phones are set up for this person.

    A family had no way to tell whether the phone on the side table was
    working, and neither did CareBridge. Notification tokens are never
    included: the dashboard has no use for a phone's address.
    """
    firestore = deps.firestore_service()
    require_elder_access(elder_id, caregiver_id, firestore)

    return firestore.list_devices_for_elder(elder_id)


@router.get("/elders/{elder_id}/history")
def get_history(
    elder_id: str,
    days: int = 7,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """How the last week went, one line per day.

    "Has she been taking it?" is the question families actually carry, and the
    one a doctor asks at the next appointment. Every event was already stored;
    nothing read them back until now.
    """
    days = max(1, min(days, 31))

    firestore = deps.firestore_service()
    elder = require_elder_access(elder_id, caregiver_id, firestore)
    tz = _elder_zone(elder)

    local_now = datetime.now(tz)
    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)

    events = deps.event_service().list_events_for_elder_between(
        elder_id, start, today + timedelta(days=1)
    )

    by_day: dict[str, list[dict]] = {
        (start + timedelta(days=offset)).date().isoformat(): []
        for offset in range(days)
    }

    for event in events:
        day = event["scheduled_at"].astimezone(tz).date().isoformat()
        if day in by_day:
            by_day[day].append(event)

    # The same counting rule as today's headline, so a day cannot read one way
    # in the strip and another way when you open it.
    return {
        "elder": {"id": elder["id"], "name": elder["name"], "timezone": str(tz)},
        "days": [
            {"date": day, **build_ledger(group).to_dict()}
            for day, group in by_day.items()
        ],
    }


def _unmaterialised_status(local_time: str, local_now: datetime) -> str:
    """Classifies a scheduled time the worker has not turned into an event.

    A time still to come is UPCOMING. A time already past means no reminder was
    ever sent for it — worth saying plainly rather than calling it upcoming,
    which is what the dashboard used to do for every unmaterialised time.

    The grace window keeps a time that passed moments ago out of MISSED: the
    worker only runs once a minute, so it has not had its chance yet.
    """
    try:
        hour, minute = (int(part) for part in local_time.split(":"))
    except (ValueError, AttributeError):
        return "UPCOMING"

    scheduled = local_now.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    return "UPCOMING" if scheduled > local_now - MISSED_GRACE else "MISSED"

@router.delete("/devices/{elder_id}", status_code=204)
def unregister_device(
    elder_id: str,
    fcm_token: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Takes one person off a phone without unpairing anyone else on it.

    Removing a phone from the list has to remove its access, not just its
    notifications — a device that still reads the medication record is not
    unpaired in any sense a caregiver would recognise. Sessions are held per
    elder, so this signs that elder's other devices out too and they need a
    fresh pairing code. Anyone else on a shared handset is untouched.
    """
    firestore = deps.firestore_service()
    require_elder_access(elder_id, caregiver_id, firestore)

    firestore.unregister_device(elder_id=elder_id, fcm_token=fcm_token)
    revoke_elder_sessions(elder_id)


@router.post("/elders/{elder_id}/devices/sign-out")
def sign_out_devices(
    elder_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Signs every one of an elder's devices out at once.

    For the phone that is lost, stolen, or went home with a carer who no longer
    works for the family. Unregistering by FCM token cannot help there: the
    token lives on the handset you no longer have.
    """
    firestore = deps.firestore_service()
    elder = require_elder_access(elder_id, caregiver_id, firestore)

    unpaired = firestore.deactivate_devices_for_elder(elder_id)
    revoke_elder_sessions(elder_id)

    return {
        "elder_id": elder_id,
        "elder_name": elder["name"],
        "devices_signed_out": unpaired,
    }


@router.get("/elders/{elder_id}/today")
def get_today(
    elder_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """What the caregiver dashboard renders: today's plan and where it stands."""
    firestore = deps.firestore_service()
    elder = require_elder_access(elder_id, caregiver_id, firestore)

    tz = _elder_zone(elder)
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

        # A removed medication leaves today's events behind. Showing them is
        # what made Remove look like it had done nothing at all. A course that
        # has since been shortened leaves them behind in exactly the same way.
        if not medication or not medication.get("active", True):
            continue
        if not course.runs_on(medication, local_now.date()):
            continue

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
            # False means no reminder physically left the building, whatever
            # the attempt count says.
            "reached_a_phone": bool(event.get("reached_a_phone")),
            # Recorded on her own device, or taken on the family's word. A week
            # that is only green because somebody ticked it off from another
            # city is a different week, and the row should say so.
            "confirmed_source": event.get("confirmed_source"),
            # She answered and CareBridge could not tell what she meant. Not a
            # status — the dose did not move — but the family should see it.
            "unclear_count": event.get("unclear_count", 0),
            "last_unclear": (event.get("unclear_replies") or [{}])[-1].get("heard"),
            "confirmed_at": event.get("confirmed_at"),
            "acknowledged_at": event.get("acknowledged_at"),
            "escalated_at": event.get("escalated_at"),
            "next_attempt_at": event.get("next_attempt_at"),
            "course": course.progress(medication, local_now.date()),
        })

    # Times that have not been materialised into events yet still belong on the
    # dashboard, otherwise the day looks empty until the first reminder fires.
    materialised = {(e["medication_id"], e["local_time"]) for e in items}
    for medication in firestore.list_medications_for_elder(elder_id):
        if not course.runs_on(medication, local_now.date()):
            continue
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
                "status": _unmaterialised_status(value, local_now),
                "attempt": 0,
                "max_attempts": medication.get("max_attempts"),
                # Nothing has been attempted for a time the worker has not
                # reached yet, so there is nothing to have failed at.
                "reached_a_phone": True,
                "confirmed_source": None,
                "unclear_count": 0,
                "last_unclear": None,
                "confirmed_at": None,
                "acknowledged_at": None,
                "escalated_at": None,
                "next_attempt_at": None,
                "course": course.progress(medication, local_now.date()),
            })

    return {
        "elder": {"id": elder["id"], "name": elder["name"], "timezone": str(tz)},
        "date": local_now.date().isoformat(),
        "items": sorted(items, key=lambda i: i["local_time"]),
        "ledger": build_ledger(events + _unmaterialised(items)).to_dict(),
    }


def _unmaterialised(items: list[dict]) -> list[dict]:
    """Scheduled times the worker never turned into events, counted honestly.

    They are real doses on a real plan, so leaving them out of the denominator
    flatters the day. But nothing was ever delivered for them either — a time
    already past with no event behind it means no reminder went out at all,
    which is usually the scheduler stopped, not the elder ignoring anything.

    Shaped like events so there is one counting rule rather than two.
    """
    return [
        {
            "status": "PENDING",
            "reached_a_phone": False,
            # A past time that never became an event has already failed;
            # one still ahead has not been tried yet.
            "attempt": 1 if item["status"] == "MISSED" else 0,
        }
        for item in items
        if item["event_id"] is None
        and item["status"] in ("MISSED", "UPCOMING")
    ]


@router.get("/elders/{elder_id}/insight")
async def get_insight(
    elder_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """The short weekly note: how the week went, and whether that is new.

    The figures are computed in adherence_service and are already final when
    this runs. The analyst agent is asked only to phrase them, and if it is
    off, slow or unavailable the deterministic sentence is returned instead —
    so the weekly note is a feature of CareBridge rather than a feature of
    Gemini being up. `narrated` says which one you are reading.
    """
    firestore = deps.firestore_service()
    require_elder_access(elder_id, caregiver_id, firestore)

    brief = deps.adherence_service().weekly_brief(elder_id)
    plain = plain_weekly_note(brief)

    from app.services.narration_service import NarrationService

    narrated = await NarrationService().narrate(
        "weekly", brief, f"{elder_id}_{brief['week_starting']}"
    )

    return {
        "elder_id": elder_id,
        "week_starting": brief["week_starting"],
        "note": narrated or plain,
        "narrated": bool(narrated),
        "plain_note": plain,
        "this_week": brief["this_week"],
        "usual": brief["usual"],
        "what_changed": brief["what_changed"],
    }


@router.post("/elders/{elder_id}/self-test")
def run_self_test(
    elder_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Proves the whole chain works, before the evening it has to.

    Every silent failure this project has actually hit is on this list: a phone
    that was never paired, a caregiver with no address on file, SMTP that was
    never configured, a timezone left on the setter-up's own. Each one is
    invisible until a dose is missed, and by then the answer arrives as
    "she has not confirmed" — which reads as a person, not as plumbing.

    Sends a real notification. Creates no dose and changes no record.
    """
    firestore = deps.firestore_service()
    elder = require_elder_access(elder_id, caregiver_id, firestore)

    push = deps.notification_service().send_self_test(elder)
    settings = get_settings()

    caregivers = [
        firestore.get_caregiver(cid) or {}
        for cid in (elder.get("caregiver_ids") or [])
    ]
    with_email = [c for c in caregivers if c.get("email")]
    medications = firestore.list_medications_for_elder(elder_id)

    checks = [
        {
            "check": "A phone is paired",
            "ok": push["devices"] > 0,
            "detail": (
                f"{push['devices']} paired"
                if push["devices"]
                else f"No phone is set up, so nothing can reach {elder['name']}."
            ),
        },
        {
            "check": "The notification arrived",
            "ok": push["delivered_to"] > 0,
            "detail": (
                f"Sent to {push['delivered_to']} of {push['devices']}."
                if push["devices"]
                else "Nothing to send to yet."
            ),
        },
        {
            "check": "Somebody is on file to be told",
            "ok": bool(with_email),
            "detail": (
                ", ".join(c["email"] for c in with_email)
                if with_email
                else "No email address on file, so an escalation has nowhere to go."
            ),
        },
        {
            "check": "Escalation email is configured",
            "ok": settings.email_configured,
            "detail": (
                "Ready."
                if settings.email_configured
                else "SMTP is not set up on this deployment."
            ),
        },
        {
            "check": f"{elder['name']}'s timezone is set",
            "ok": bool(elder.get("timezone")),
            "detail": elder.get("timezone") or "Not set — doses would be hours out.",
        },
        {
            "check": "There is something to remind about",
            "ok": bool(medications),
            "detail": f"{len(medications)} active",
        },
    ]

    return {
        "elder_id": elder_id,
        "ok": all(c["ok"] for c in checks),
        "checks": checks,
    }
