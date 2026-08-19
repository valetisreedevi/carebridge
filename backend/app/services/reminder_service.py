import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import get_settings
from app.models.medication_event import MedicationEventStatus
from app.services.firestore_service import FirestoreService, get_db
from app.services.medication_event_service import (
    MedicationEventService,
    event_document_id,
)
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

# How far ahead of a scheduled time an event is created, so the first reminder
# fires promptly rather than up to a minute late.
MATERIALISE_AHEAD = timedelta(minutes=5)


def _zone(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


class ReminderService:
    """Everything Cloud Scheduler triggers once a minute.

    Two passes: turn medication schedules into concrete events, then act on
    every event whose next attempt is due.
    """

    def __init__(self, db=None):
        self.db = db or get_db()
        self.firestore = FirestoreService(self.db)
        self.events = MedicationEventService(self.db)
        self.notifications = NotificationService(self.db)
        self.settings = get_settings()

    # ---------------- pass 1: materialise ----------------

    def materialise_due_events(self, now: datetime) -> list[dict]:
        created = []

        for medication in self.firestore.list_active_medications():
            elder = self.firestore.get_elder(medication["elder_id"])
            if not elder:
                continue

            for occurrence in self._occurrences_today(medication, elder, now):
                if occurrence > now + MATERIALISE_AHEAD:
                    continue

                event_id = event_document_id(medication["id"], occurrence)
                _, was_created = self.events.create_event_if_absent(
                    event_id=event_id,
                    medication_id=medication["id"],
                    elder_id=elder["id"],
                    scheduled_at=occurrence,
                    retry_after_minutes=medication.get(
                        "retry_after_minutes", self.settings.default_retry_after_minutes
                    ),
                    max_attempts=medication.get(
                        "max_attempts", self.settings.default_max_attempts
                    ),
                )

                if was_created:
                    created.append({
                        "event_id": event_id,
                        "medication_id": medication["id"],
                        "elder_id": elder["id"],
                        "scheduled_at": occurrence.isoformat(),
                    })

        return created

    def _occurrences_today(
        self,
        medication: dict,
        elder: dict,
        now: datetime,
    ) -> list[datetime]:
        """Scheduled times expressed in the elder's local day, as UTC instants."""
        tz = _zone(elder.get("timezone"))
        local_now = now.astimezone(tz)

        times = medication.get("schedule_times")
        if not times:
            single = medication.get("schedule_time")
            times = [single] if single else []

        occurrences = []
        for value in times:
            try:
                hour, minute = (int(part) for part in value.split(":"))
            except (ValueError, AttributeError):
                logger.warning(
                    "Medication %s has an unusable schedule time %r",
                    medication["id"],
                    value,
                )
                continue

            occurrences.append(
                local_now.replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                ).astimezone(timezone.utc)
            )

        return occurrences

    # ---------------- pass 2: act on due events ----------------

    def process_due_events(self, now: datetime) -> dict:
        reminded = []
        escalated = []

        for event in self.events.get_due_events(now):
            status = MedicationEventStatus(event["status"])
            attempt = event.get("attempt", 0)
            max_attempts = event.get("max_attempts", self.settings.default_max_attempts)

            medication = self.firestore.get_medication(event["medication_id"])
            elder = self.firestore.get_elder(event["elder_id"])

            if not medication or not elder:
                logger.warning("Event %s references missing documents", event["id"])
                self.events.cancel_event(event["id"])
                continue

            # A snooze always earns another reminder, even past max_attempts:
            # the elder asked for it, so it is not an unanswered attempt.
            out_of_attempts = (
                attempt >= max_attempts and status is not MedicationEventStatus.SNOOZED
            )

            if out_of_attempts:
                escalated.append(self._escalate(event, elder, medication))
            else:
                reminded.append(self._remind(event, elder, medication, now))

        return {
            "processed_at": now.isoformat(),
            "reminders_sent": reminded,
            "escalations": escalated,
        }

    def _remind(self, event: dict, elder: dict, medication: dict, now: datetime) -> dict:
        self.notifications.send_reminder(elder, medication, event)
        updated = self.events.record_reminder_sent(event["id"], now)

        return {
            "event_id": event["id"],
            "elder": elder["name"],
            "medication": medication["name"],
            "attempt": updated["attempt"],
            "next_attempt_at": updated["next_attempt_at"].isoformat(),
        }

    def _escalate(self, event: dict, elder: dict, medication: dict) -> dict:
        local_time = event["scheduled_at"].astimezone(_zone(elder.get("timezone")))

        # Wording matters: no response is "not confirmed", never "not taken".
        message = (
            f"{elder['name']} has not confirmed the "
            f"{local_time.strftime('%I:%M %p').lstrip('0')} {medication['name']} "
            f"after {event.get('attempt', 0)} reminder attempts."
        )

        self.events.escalate_event(event["id"])
        self.notifications.notify_caregiver(
            elder,
            medication,
            event,
            reason="NOT_CONFIRMED",
            message=message,
        )

        return {
            "event_id": event["id"],
            "elder": elder["name"],
            "medication": medication["name"],
            "message": message,
        }

    # ---------------- entry point ----------------

    def run(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        created = self.materialise_due_events(now)
        result = self.process_due_events(now)
        return {"events_created": created, **result}
