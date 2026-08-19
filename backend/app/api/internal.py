import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import current_caregiver_id, require_elder_access, require_worker_token
from app.api import deps
from app.api.schemas import TriggerReminderRequest
from app.services.medication_event_service import event_document_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["worker"])


@router.post("/internal/reminders/process", dependencies=[Depends(require_worker_token)])
def process_reminders():
    """Called by Cloud Scheduler every minute."""
    result = deps.reminder_service().run()

    logger.info(
        "Worker run: %s created, %s reminded, %s escalated",
        len(result["events_created"]),
        len(result["reminders_sent"]),
        len(result["escalations"]),
    )
    return result


@router.get("/caregivers/me/alerts")
def list_alerts(caregiver_id: str = Depends(current_caregiver_id)):
    return deps.notification_service().list_for_caregiver(caregiver_id)


@router.post("/demo/trigger-reminder")
def trigger_reminder(
    request: TriggerReminderRequest,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """Fires a medication immediately so a demo does not wait for the clock."""
    firestore = deps.firestore_service()
    medication = firestore.get_medication(request.medication_id)

    if not medication:
        raise HTTPException(status_code=404, detail="Medication not found")

    elder = require_elder_access(medication["elder_id"], caregiver_id, firestore)

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    event_id = event_document_id(medication["id"], now)

    events = deps.event_service()
    events.create_event(
        event_id=event_id,
        medication_id=medication["id"],
        elder_id=elder["id"],
        scheduled_at=now,
        retry_after_minutes=medication.get("retry_after_minutes", 10),
        max_attempts=medication.get("max_attempts", 2),
    )

    result = deps.reminder_service().process_due_events(now)
    return {"event_id": event_id, **result}
