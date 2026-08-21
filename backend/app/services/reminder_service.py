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

# How long after its scheduled time a dose may still be raised. Past this the
# worker stays quiet: telling someone at 11:00 to take a 07:00 dose invites a
# double dose, which is worse than the reminder they already missed. Whatever
# went stale is surfaced to the caregiver instead.
MATERIALISE_STALE_AFTER = timedelta(hours=2)


def _zone(name: str | None) -> ZoneInfo:
    """The elder's own day, falling back to UTC — but never quietly.

    A missing or unresolvable zone puts every dose hours from where the family
    meant it, and the only symptom is reminders at the wrong time of day.
    Refusing outright would be worse: it would stop that household's reminders
    altogether. So it carries on, and says so.
    """
    if not name:
        logger.warning("Elder has no timezone; scheduling their day in UTC")
        return ZoneInfo("UTC")

    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        logger.warning("Timezone %r is unknown here; scheduling in UTC", name)
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

                if occurrence < now - MATERIALISE_STALE_AFTER:
                    logger.info(
                        "Skipping stale occurrence %s for medication %s",
                        occurrence.isoformat(),
                        medication["id"],
                    )
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

        # One buzz per person per pass, however many tablets are due. Three
        # separate alerts is how someone learns to ignore the phone; the push
        # only wakes the device, which then fetches the whole queue.
        already_alerted: set[str] = set()

        # Whether there is anywhere to send at all, asked once per person
        # rather than per dose. Only the first event of a batch pushes, so the
        # others cannot learn this from their own send.
        reachable: dict[str, bool] = {}

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

            # A medication removed after its event was created still has a live
            # next_attempt_at. Without this the worker keeps reminding, and
            # eventually escalates, a medicine the caregiver deleted.
            if not medication.get("active", True):
                logger.info(
                    "Cancelling event %s: medication %s was removed",
                    event["id"],
                    medication["id"],
                )
                self.events.cancel_event(event["id"])
                continue

            # Already handed over. What is still running is the ladder of ways
            # to reach the caregiver, not the reminder itself.
            if status is MedicationEventStatus.ESCALATED:
                followed = self._follow_up(event, elder, medication, now)
                if followed:
                    escalated.append(followed)
                continue

            if self._is_exhausted(event, status, attempt, max_attempts, now):
                escalated.append(
                    self._escalate(event, elder, medication, now, status)
                )
            else:
                alert = elder["id"] not in already_alerted
                already_alerted.add(elder["id"])

                if elder["id"] not in reachable:
                    reachable[elder["id"]] = bool(
                        self.firestore.get_device_tokens(elder["id"])
                    )

                reminded.append(
                    self._remind(
                        event, elder, medication, now, alert, reachable[elder["id"]]
                    )
                )

        return {
            "processed_at": now.isoformat(),
            "reminders_sent": reminded,
            "escalations": escalated,
        }

    def _is_exhausted(
        self,
        event: dict,
        status: MedicationEventStatus,
        attempt: int,
        max_attempts: int,
        now: datetime,
    ) -> bool:
        """Whether the caregiver should now be told.

        A snooze is a real answer, so it never burns an attempt — but confusion
        and fatigue look exactly like snoozing forever, and the person putting a
        dose off all morning is the one somebody should hear about. So a snooze
        is exempt only until it has been used a few times, or until the dose is
        simply too late to keep waiting on.
        """
        if status is not MedicationEventStatus.SNOOZED:
            return attempt >= max_attempts

        too_many = event.get("snooze_count", 0) >= self.settings.max_snoozes
        too_late = now >= event["scheduled_at"] + timedelta(
            minutes=self.settings.escalate_after_minutes
        )
        return too_many or too_late

    def _remind(
        self,
        event: dict,
        elder: dict,
        medication: dict,
        now: datetime,
        alert: bool = True,
        reachable: bool = True,
    ) -> dict:
        """Records an attempt, and optionally rings the phone about it.

        Every due dose still counts as reminded — each keeps its own attempt
        count and escalates on its own — but only the first of a batch makes a
        sound.

        Whether anything actually left the building is remembered on the event.
        A household with no phone set up still runs the full count and then
        tells the family she "has not confirmed", which reads as a person
        ignoring her tablets when the truth is that nobody ever asked her.
        """
        if alert:
            self.notifications.send_reminder(elder, medication, event)

        updated = self.events.record_reminder_sent(event["id"], now, reached=reachable)

        return {
            "event_id": event["id"],
            "elder": elder["name"],
            "medication": medication["name"],
            "attempt": updated["attempt"],
            "alerted": alert,
            "reached_a_phone": updated["reached_a_phone"],
            "next_attempt_at": updated["next_attempt_at"].isoformat(),
        }

    def _next_step_at(self, level: int, now: datetime) -> datetime | None:
        """When to try the next channel, or None if there is no next channel."""
        if level + 1 >= len(self.settings.escalation_channels):
            return None
        return now + timedelta(minutes=self.settings.escalation_step_minutes)

    def _follow_up(
        self,
        event: dict,
        elder: dict,
        medication: dict,
        now: datetime,
    ) -> dict | None:
        """Tries the next way of reaching the caregiver, unless they answered.

        An acknowledgement stops the ladder immediately: someone saying they
        have it in hand is the point of the whole thing, and continuing to
        chase them is how a family learns to mute the app.
        """
        if event.get("acknowledged_at"):
            self.events.advance_escalation(
                event["id"], event.get("escalation_level", 0), None
            )
            return None

        channels = self.settings.escalation_channels
        level = event.get("escalation_level", 0) + 1

        if level >= len(channels):
            self.events.advance_escalation(event["id"], level - 1, None)
            return None

        message = event.get("escalation_message") or (
            f"{elder['name']} still has not taken the {medication['name']}."
        )

        self.notifications.notify_caregiver(
            elder,
            medication,
            event,
            reason=event.get("escalation_reason") or "NOT_CONFIRMED",
            message=message,
            channel=channels[level],
        )
        self.events.advance_escalation(
            event["id"], level, self._next_step_at(level, now)
        )

        return {
            "event_id": event["id"],
            "elder": elder["name"],
            "medication": medication["name"],
            "channel": channels[level],
            "reason": event.get("escalation_reason") or "NOT_CONFIRMED",
            "message": message,
        }

    def _escalate(
        self,
        event: dict,
        elder: dict,
        medication: dict,
        now: datetime,
        status: MedicationEventStatus | None = None,
    ) -> dict:
        local_time = event["scheduled_at"].astimezone(_zone(elder.get("timezone")))
        when = local_time.strftime("%I:%M %p").lstrip("0")

        # Wording matters: no response is "not confirmed", never "not taken".
        # Someone who kept snoozing did answer, so they are described honestly
        # rather than lumped in with silence.
        reason = "NOT_CONFIRMED"

        if not event.get("reached_a_phone"):
            # Nothing was ever delivered, so she was never asked. Reporting
            # this as an unanswered reminder sends the family to blame a person
            # for a phone that was never set up — the exact misunderstanding
            # CareBridge exists to remove.
            reason = "UNREACHABLE"
            message = (
                f"CareBridge could not reach {elder['name']}'s phone, so the "
                f"{when} {medication['name']} was never asked about. "
                "Check the phone is set up."
            )
        elif status is MedicationEventStatus.SNOOZED:
            message = (
                f"{elder['name']} has put off the {when} {medication['name']} "
                f"{event.get('snooze_count', 0)} times and still has not taken it."
            )
        else:
            message = (
                f"{elder['name']} has not confirmed the "
                f"{when} {medication['name']} "
                f"after {event.get('attempt', 0)} reminder attempts."
            )

        # The worker's clock, not wall-clock: a run working through a backlog
        # must schedule the next rung relative to the alert it just sent.
        channels = self.settings.escalation_channels

        self.events.escalate_event(event["id"], self._next_step_at(0, now))
        # Kept so a later rung says the same thing the first one did.
        self.events._ref(event["id"]).update(
            {"escalation_message": message, "escalation_reason": reason}
        )

        self.notifications.notify_caregiver(
            elder,
            medication,
            event,
            reason=reason,
            message=message,
            channel=channels[0] if channels else "push",
        )

        return {
            "event_id": event["id"],
            "elder": elder["name"],
            "medication": medication["name"],
            "channel": channels[0] if channels else "push",
            "reason": reason,
            "message": message,
        }

    # ---------------- things a caregiver asks for directly ----------------

    def _event_for(self, medication: dict, occurrence: datetime) -> str:
        """The event for one scheduled instant, created if it never happened."""
        event_id = event_document_id(medication["id"], occurrence)

        self.events.create_event_if_absent(
            event_id=event_id,
            medication_id=medication["id"],
            elder_id=medication["elder_id"],
            scheduled_at=occurrence,
            retry_after_minutes=medication.get(
                "retry_after_minutes", self.settings.default_retry_after_minutes
            ),
            max_attempts=medication.get(
                "max_attempts", self.settings.default_max_attempts
            ),
        )
        return event_id

    def remind_immediately(self, medication: dict) -> dict:
        """Rings the elder's phone about one medicine, now.

        Deliberately not a worker pass. Running process_due_events here acted on
        every household whose dose happened to be due at that moment — sending
        their reminders and advancing their attempt counts off the back of one
        caregiver's button — and handed their names and medicines back in the
        response. A caregiver's action touches their own elder or nothing.
        """
        elder = self.firestore.get_elder(medication["elder_id"])
        if not elder:
            raise LookupError(medication["elder_id"])

        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        event_id = self._event_for(medication, now)
        event = self.events.get_event(event_id)

        return {"event_id": event_id, **self._remind(event, elder, medication, now)}

    def confirm_on_behalf(
        self,
        medication: dict,
        local_time: str,
        caregiver_id: str,
    ) -> dict:
        """Closes one of today's doses on the caregiver's word."""
        elder = self.firestore.get_elder(medication["elder_id"])
        if not elder:
            raise LookupError(medication["elder_id"])

        occurrence = self._occurrence_at(elder, local_time)
        event_id = self._event_for(medication, occurrence)
        updated = self.events.confirm_by_caregiver(event_id, caregiver_id)

        return {
            "event_id": event_id,
            "status": updated["status"],
            "confirmed_at": updated["confirmed_at"],
            "confirmed_source": updated["confirmed_source"],
        }

    def _occurrence_at(self, elder: dict, local_time: str) -> datetime:
        """Today's instant for a wall-clock time in the elder's own day."""
        tz = _zone(elder.get("timezone"))
        hour, minute = (int(part) for part in local_time.split(":"))

        return (
            datetime.now(tz)
            .replace(hour=hour, minute=minute, second=0, microsecond=0)
            .astimezone(timezone.utc)
        )

    # ---------------- entry point ----------------

    def run(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        created = self.materialise_due_events(now)
        result = self.process_due_events(now)
        return {"events_created": created, **result}
