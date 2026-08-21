import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import current_caregiver_id, require_elder_access, require_worker_token
from app.api import deps

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


@router.post("/medication-events/{event_id}/acknowledge")
def acknowledge_alert(
    event_id: str,
    caregiver_id: str = Depends(current_caregiver_id),
):
    """"I have got this" — stops CareBridge chasing the caregiver.

    Separate from marking the dose taken: knowing about a missed dose is not
    the same as it having been swallowed, and the record must not blur them.
    """
    events = deps.event_service()
    event = events.get_event(event_id)

    if not event:
        raise HTTPException(status_code=404, detail="Reminder not found")

    require_elder_access(event["elder_id"], caregiver_id, deps.firestore_service())
    updated = events.acknowledge_event(event_id, caregiver_id)

    return {
        "event_id": event_id,
        "acknowledged_at": updated["acknowledged_at"],
        "status": updated["status"],
    }
