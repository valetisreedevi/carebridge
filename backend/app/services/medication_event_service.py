from datetime import date, datetime, timedelta, timezone

from google.cloud import firestore

from app.models.medication_event import (
    InvalidTransition,
    MedicationEventStatus,
    can_transition,
)
from app.services.firestore_service import get_db

COLLECTION = "medication_events"


def event_document_id(medication_id: str, occurrence: datetime) -> str:
    """Deterministic id so the worker can materialise events idempotently."""
    return f"{medication_id}_{occurrence.strftime('%Y%m%dT%H%M')}"


class MedicationEventService:

    def __init__(self, db: firestore.Client | None = None):
        self.db = db or get_db()

    def _ref(self, event_id: str):
        return self.db.collection(COLLECTION).document(event_id)

    def get_event(self, event_id: str) -> dict | None:
        snapshot = self._ref(event_id).get()
        if not snapshot.exists:
            return None
        return {"id": snapshot.id, **snapshot.to_dict()}

    def create_event(
        self,
        medication_id: str,
        elder_id: str,
        scheduled_at: datetime,
        retry_after_minutes: int,
        max_attempts: int,
        event_id: str | None = None,
    ) -> str:
        ref = (
            self._ref(event_id)
            if event_id
            else self.db.collection(COLLECTION).document()
        )

        ref.set({
            "medication_id": medication_id,
            "elder_id": elder_id,
            "scheduled_at": scheduled_at,
            "status": MedicationEventStatus.PENDING.value,
            "attempt": 0,
            "max_attempts": max_attempts,
            "retry_after_minutes": retry_after_minutes,
            # The worker polls on this field. Terminal states clear it.
            "next_attempt_at": scheduled_at,
            "confirmed_at": None,
            "declined_at": None,
            "escalated_at": None,
            "created_at": datetime.now(timezone.utc),
        })
        return ref.id

    def create_event_if_absent(self, **kwargs) -> tuple[str, bool]:
        event_id = kwargs["event_id"]
        if self._ref(event_id).get().exists:
            return event_id, False
        return self.create_event(**kwargs), True

    # ---------------- transitions ----------------

    def _transition(
        self,
        event_id: str,
        requested: MedicationEventStatus,
        extra: dict,
    ) -> dict:
        """Apply a state change atomically, rejecting illegal transitions."""

        @firestore.transactional
        def apply(transaction, ref):
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                raise KeyError(event_id)

            data = snapshot.to_dict()
            current = MedicationEventStatus(data["status"])

            if not can_transition(current, requested):
                raise InvalidTransition(current, requested)

            updates = {"status": requested.value, **extra}
            transaction.update(ref, updates)
            return {"id": event_id, **data, **updates}

        return apply(self.db.transaction(), self._ref(event_id))

    def record_reminder_sent(
        self,
        event_id: str,
        now: datetime | None = None,
    ) -> dict:
        """Called by the worker after a reminder is dispatched.

        The retry is measured from the worker's clock, not wall-clock time, so
        a run processing a backlog schedules retries relative to the reminder
        it just sent.
        """
        now = now or datetime.now(timezone.utc)

        @firestore.transactional
        def apply(transaction, ref):
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                raise KeyError(event_id)

            data = snapshot.to_dict()
            current = MedicationEventStatus(data["status"])
            requested = MedicationEventStatus.REMINDER_SENT

            if not can_transition(current, requested):
                raise InvalidTransition(current, requested)

            attempt = data.get("attempt", 0) + 1
            retry_after = data.get("retry_after_minutes", 10)

            updates = {
                "status": requested.value,
                "attempt": attempt,
                "last_attempt_at": now,
                "next_attempt_at": now + timedelta(minutes=retry_after),
            }
            transaction.update(ref, updates)
            return {"id": event_id, **data, **updates}

        return apply(self.db.transaction(), self._ref(event_id))

    def confirm_event(self, event_id: str) -> dict:
        return self._transition(
            event_id,
            MedicationEventStatus.TAKEN,
            {
                "confirmed_at": datetime.now(timezone.utc),
                "next_attempt_at": None,
            },
        )

    def decline_event(self, event_id: str, reason: str | None = None) -> dict:
        return self._transition(
            event_id,
            MedicationEventStatus.DECLINED,
            {
                "declined_at": datetime.now(timezone.utc),
                "decline_reason": reason,
                "next_attempt_at": None,
            },
        )

    def snooze_event(
        self,
        event_id: str,
        minutes: int,
        now: datetime | None = None,
    ) -> dict:
        now = now or datetime.now(timezone.utc)

        return self._transition(
            event_id,
            MedicationEventStatus.SNOOZED,
            {
                "next_attempt_at": now + timedelta(minutes=minutes),
                "snoozed_minutes": minutes,
            },
        )

    def escalate_event(self, event_id: str) -> dict:
        return self._transition(
            event_id,
            MedicationEventStatus.ESCALATED,
            {
                "escalated_at": datetime.now(timezone.utc),
                "next_attempt_at": None,
            },
        )

    def cancel_event(self, event_id: str) -> dict:
        return self._transition(
            event_id,
            MedicationEventStatus.CANCELLED,
            {"next_attempt_at": None},
        )

    # ---------------- queries ----------------

    def get_due_events(self, now: datetime, limit: int = 200) -> list[dict]:
        """Events whose next attempt time has arrived.

        Terminal states set next_attempt_at to None, which Firestore's range
        filter excludes, so a single inequality covers the whole worker query.
        """
        query = (
            self.db.collection(COLLECTION)
            .where(filter=firestore.FieldFilter("next_attempt_at", "<=", now))
            .order_by("next_attempt_at")
            .limit(limit)
        )
        return [{"id": d.id, **d.to_dict()} for d in query.stream()]

    def _for_elder(self, elder_id: str) -> list[dict]:
        """One elder's events.

        Filtered on a single field so Firestore's automatic single-field
        indexes suffice; the day and status narrowing happens in Python, which
        is cheap at one household's volume.
        """
        query = self.db.collection(COLLECTION).where(
            filter=firestore.FieldFilter("elder_id", "==", elder_id)
        )
        return [{"id": d.id, **d.to_dict()} for d in query.stream()]

    def list_events_for_elder_on(
        self,
        elder_id: str,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        events = [
            e for e in self._for_elder(elder_id) if start <= e["scheduled_at"] < end
        ]
        return sorted(events, key=lambda e: e["scheduled_at"])

    def get_active_event_for_elder(self, elder_id: str) -> dict | None:
        """The reminder the elder is currently being asked about."""
        open_statuses = {
            MedicationEventStatus.REMINDER_SENT.value,
            MedicationEventStatus.SNOOZED.value,
        }
        events = [
            e for e in self._for_elder(elder_id) if e["status"] in open_statuses
        ]
        if not events:
            return None
        return max(events, key=lambda e: e["scheduled_at"])
