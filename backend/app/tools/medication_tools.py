"""The only database access the agent has.

Every tool resolves the elder from an ambient request context rather than an
argument, so the model cannot reach another family's records by inventing an
id. Tools report failures as data; they never raise into the model.
"""

import logging
from contextvars import ContextVar
from dataclasses import dataclass

from app.config import get_settings
from app.models.medication import FOOD_INSTRUCTION_TEXT, FoodInstruction
from app.models.medication_event import InvalidTransition
from app.services.firestore_service import FirestoreService
from app.services.medication_event_service import MedicationEventService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

MAX_SNOOZE_MINUTES = 60
MIN_SNOOZE_MINUTES = 1


@dataclass
class AgentContext:
    elder_id: str
    event_id: str | None


_context: ContextVar[AgentContext | None] = ContextVar("agent_context", default=None)


def set_context(context: AgentContext) -> None:
    _context.set(context)


def _resolve() -> tuple[AgentContext | None, dict | None, str | None]:
    """Returns (context, event, error message)."""
    context = _context.get()
    if context is None:
        return None, None, "No active reminder context."

    if not context.event_id:
        return context, None, "There is no reminder in progress right now."

    event = MedicationEventService().get_event(context.event_id)
    if not event:
        return context, None, "That reminder could not be found."

    # Defence in depth: the event must belong to the elder in this session.
    if event["elder_id"] != context.elder_id:
        logger.error("Context/event elder mismatch for event %s", context.event_id)
        return context, None, "That reminder could not be found."

    return context, event, None


def _food_text(medication: dict) -> str:
    try:
        return FOOD_INSTRUCTION_TEXT[FoodInstruction(medication.get("food_instruction"))]
    except ValueError:
        return "as instructed"


def get_current_reminder() -> dict:
    """Get the medication reminder the elder is being asked about right now.

    Call this first in any conversation so that the name, dose and food
    instruction you mention are the ones the caregiver actually configured, and
    so that you know which language to speak. Never describe a medication that
    this tool did not return.
    """
    context, event, error = _resolve()
    if error:
        return {"success": False, "message": error}

    firestore = FirestoreService()
    medication = firestore.get_medication(event["medication_id"])
    if not medication:
        return {"success": False, "message": "That medication could not be found."}

    elder = firestore.get_elder(context.elder_id) or {}

    return {
        "success": True,
        # Which language to answer in. A household that never set one gets
        # English, which is the same fallback the elder screen uses.
        "speak_language": elder.get("preferred_language") or "en",
        "medication_name": medication.get("name"),
        "dose": medication.get("dose"),
        "food_instruction": _food_text(medication),
        "scheduled_time": medication.get("schedule_time"),
        "status": event["status"],
        "attempt": event.get("attempt", 0),
    }


def get_medication_instructions() -> dict:
    """Get the full instructions the caregiver recorded for this medication.

    Use this when the elder asks how or when to take the medicine. Report the
    configured instruction exactly. Do not add medical guidance of your own; if
    the elder needs advice beyond what is recorded here, tell them to check
    with their caregiver, doctor or pharmacist.
    """
    _, event, error = _resolve()
    if error:
        return {"success": False, "message": error}

    medication = FirestoreService().get_medication(event["medication_id"])
    if not medication:
        return {"success": False, "message": "That medication could not be found."}

    return {
        "success": True,
        "medication_name": medication.get("name"),
        "dose": medication.get("dose"),
        "food_instruction": _food_text(medication),
        "notes": medication.get("notes") or "",
        "schedule_time": medication.get("schedule_time"),
    }


def confirm_medication_taken() -> dict:
    """Record that the elder has taken this medication.

    Only call this when the elder has clearly said they took it. An ambiguous
    reply such as "okay", "alright" or silence is not a confirmation - ask a
    short clarifying question instead. The reminder having been delivered is
    never a reason to call this.
    """
    _, event, error = _resolve()
    if error:
        return {"success": False, "message": error}

    if event["status"] == "TAKEN":
        return {
            "success": True,
            "status": "TAKEN",
            "message": "This medication was already recorded as taken.",
        }

    try:
        MedicationEventService().confirm_event(event["id"])
    except InvalidTransition as exc:
        return {"success": False, "message": str(exc)}

    return {
        "success": True,
        "status": "TAKEN",
        "message": "Recorded as taken.",
    }


def snooze_reminder(minutes: int) -> dict:
    """Remind the elder again after the given number of minutes.

    Call this when the elder asks to be reminded later. Snoozing changes only
    when the reminder repeats - it never changes the dose, the schedule or the
    food instruction.
    """
    _, event, error = _resolve()
    if error:
        return {"success": False, "message": error}

    if minutes < MIN_SNOOZE_MINUTES or minutes > MAX_SNOOZE_MINUTES:
        return {
            "success": False,
            "message": (
                f"A reminder can only be delayed between {MIN_SNOOZE_MINUTES} and "
                f"{MAX_SNOOZE_MINUTES} minutes."
            ),
        }

    try:
        updated = MedicationEventService().snooze_event(event["id"], minutes)
    except InvalidTransition as exc:
        return {"success": False, "message": str(exc)}

    return {
        "success": True,
        "status": "SNOOZED",
        "minutes": minutes,
        "next_reminder_at": updated["next_attempt_at"].isoformat(),
    }


def record_decline(reason: str) -> dict:
    """Record that the elder does not want to take this medication.

    Call this when the elder refuses. Do not argue or try to persuade them.
    The caregiver is notified automatically.
    """
    _, event, error = _resolve()
    if error:
        return {"success": False, "message": error}

    try:
        MedicationEventService().decline_event(event["id"], reason)
    except InvalidTransition as exc:
        return {"success": False, "message": str(exc)}

    firestore = FirestoreService()
    elder = firestore.get_elder(event["elder_id"])
    medication = firestore.get_medication(event["medication_id"])

    if elder and medication:
        NotificationService().notify_caregiver(
            elder,
            medication,
            event,
            reason="DECLINED",
            message=f"{elder['name']} declined the {medication['name']}.",
        )

    return {
        "success": True,
        "status": "DECLINED",
        "message": "Recorded. Their caregiver has been told.",
    }


def report_unclear_reply(what_you_heard: str) -> dict:
    """Report that the elder said something you could not interpret.

    Call this when you genuinely cannot tell what the elder means and asking
    again has not helped - mumbling, a reply that does not answer the question,
    speech you cannot make out, or an answer about something else entirely.
    Pass what you heard as closely as you can, in their own words.

    This does not change the reminder. It keeps a record for the family, and if
    it happens repeatedly it asks them to get in touch. Prefer this over
    guessing: an unclear answer recorded honestly is worth more than a
    confirmation nobody actually gave.
    """
    context, event, error = _resolve()
    if error:
        return {"success": False, "message": error}

    settings = get_settings()
    events = MedicationEventService()

    try:
        updated = events.record_unclear_reply(event["id"], what_you_heard.strip())
    except KeyError:
        return {"success": False, "message": "That reminder could not be found."}

    count = updated.get("unclear_count", 1)
    if count < settings.max_unclear_replies:
        return {
            "success": True,
            "recorded": True,
            "caregiver_told": False,
            "message": "Noted. Ask them once more, in different words.",
        }

    # The threshold is checked here, not judged by the model. Whether somebody
    # should be interrupted is not a question a language model should be
    # answering turn by turn.
    firestore = FirestoreService()
    elder = firestore.get_elder(context.elder_id) or {}
    medication = firestore.get_medication(event["medication_id"]) or {}

    if elder:
        NotificationService().notify_caregiver(
            elder,
            medication,
            event,
            reason="NOT_UNDERSTOOD",
            message=(
                f"CareBridge could not understand {elder.get('name')} about the "
                f"{medication.get('name')}. The reply was: "
                f"\"{what_you_heard.strip()}\". "
                "Nothing has been recorded either way."
            ),
        )

    return {
        "success": True,
        "recorded": True,
        "caregiver_told": True,
        "message": "Noted, and their caregiver has been asked to get in touch.",
    }


def notify_caregiver(message: str) -> dict:
    """Ask the elder's caregiver to get in touch.

    Call this when the elder asks for help, sounds distressed or confused, or
    reports a problem such as a missing or spilled medicine. Summarise what the
    elder said in the message.
    """
    context, event, error = _resolve()

    if context is None:
        return {"success": False, "message": "No active reminder context."}

    firestore = FirestoreService()
    elder = firestore.get_elder(context.elder_id)
    if not elder:
        return {"success": False, "message": "Could not reach the caregiver."}

    medication = (
        firestore.get_medication(event["medication_id"]) if event else {}
    ) or {}

    NotificationService().notify_caregiver(
        elder,
        medication,
        event or {"id": None},
        reason="HELP_REQUESTED",
        message=f"{elder['name']}: {message}",
    )

    return {
        "success": True,
        "message": "Their caregiver has been told and will get in touch.",
    }


ALL_TOOLS = [
    get_current_reminder,
    get_medication_instructions,
    confirm_medication_taken,
    snooze_reminder,
    record_decline,
    report_unclear_reply,
    notify_caregiver,
]
