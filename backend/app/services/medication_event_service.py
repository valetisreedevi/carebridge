from datetime import date, datetime, timedelta, timezone

from google.cloud import firestore

from app.models.medication_event import (
    CAREGIVER_CONFIRMABLE,
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
        reached: bool = True,
    ) -> dict:
        """Called by the worker after a reminder is dispatched.

        The retry is measured from the worker's clock, not wall-clock time, so
        a run processing a backlog schedules retries relative to the reminder
        it just sent.

        `reached` records whether there was any phone to send to. It only ever
        goes from false to true: a dose reminded once while a phone was paired
        was genuinely asked about, whatever happened afterwards.
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
                "reached_a_phone": bool(data.get("reached_a_phone")) or reached,
            }
            transaction.update(ref, updates)
            return {"id": event_id, **data, **updates}

        return apply(self.db.transaction(), self._ref(event_id))

    def confirm_event(self, event_id: str) -> dict:
        """The elder saying so on their own device.

        An answer is proof of delivery. reached_a_phone is otherwise set only
        from FCM, so a household reached some other way — a browser holding the
        elder screen open and polling, which is exactly what a device with no
        notification permission does — recorded the dose as taken AND as never
        delivered. The dashboard then showed one taken, none asked, a bar that
        was entirely "never reached them", and a weekly note saying nobody had
        asked her about a dose she had just answered on her own screen.

        Nobody can press "I took it" on a reminder they never received.
        """
        return self._transition(
            event_id,
            MedicationEventStatus.TAKEN,
            {
                "confirmed_at": datetime.now(timezone.utc),
                "confirmed_source": "ELDER",
                "reached_a_phone": True,
                "next_attempt_at": None,
            },
        )

    def decline_event(self, event_id: str, reason: str | None = None) -> dict:
        """Also an answer, and so also proof the reminder arrived."""
        return self._transition(
            event_id,
            MedicationEventStatus.DECLINED,
            {
                "declined_at": datetime.now(timezone.utc),
                "decline_reason": reason,
                "reached_a_phone": True,
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

        # Counted, because a snooze is exempt from the attempt limit and
        # something has to stop an elder putting a dose off indefinitely.
        already = (self.get_event(event_id) or {}).get("snooze_count", 0)

        return self._transition(
            event_id,
            MedicationEventStatus.SNOOZED,
            {
                "next_attempt_at": now + timedelta(minutes=minutes),
                "snoozed_minutes": minutes,
                "snooze_count": already + 1,
                # "Remind me later" is an answer too. She saw it.
                "reached_a_phone": True,
            },
        )

    def escalate_event(self, event_id: str, next_attempt_at: datetime | None = None) -> dict:
        """Hands the dose to the caregiver.

        next_attempt_at is kept live when there are further ways to reach them,
        because a push that was never delivered must not be the end of it. The
        dose itself is finished either way; what continues is the telling.
        """
        return self._transition(
            event_id,
            MedicationEventStatus.ESCALATED,
            {
                "escalated_at": datetime.now(timezone.utc),
                "escalation_level": 0,
                "next_attempt_at": next_attempt_at,
            },
        )

    def advance_escalation(
        self,
        event_id: str,
        level: int,
        next_attempt_at: datetime | None,
    ) -> dict:
        """Moves to the next way of reaching the caregiver.

        Not a transition: the event stays ESCALATED throughout. Only how hard
        CareBridge is trying to tell somebody changes.
        """
        updates = {"escalation_level": level, "next_attempt_at": next_attempt_at}
        self._ref(event_id).update(updates)
        return {**(self.get_event(event_id) or {}), **updates}

    def record_unclear_reply(self, event_id: str, heard: str, keep: int = 5) -> dict:
        """The elder answered, and CareBridge could not tell what she meant.

        Deliberately not a status. An unintelligible reply does not move the
        dose anywhere — she has not taken it, refused it or put it off — so
        writing it into the state machine would mean inventing a lifecycle
        stage for something that is really an observation about the
        conversation. The reminder carries on exactly as it would have.

        What it does change is the count, and the count is what acts: two
        replies nobody could interpret is not a model problem to keep
        retrying, it is a person who cannot use this tonight, and somebody
        should be told while there is still time to phone.
        """

        @firestore.transactional
        def apply(transaction, ref):
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                raise KeyError(event_id)

            data = snapshot.to_dict()
            trail = list(data.get("unclear_replies") or [])
            trail.append({"at": datetime.now(timezone.utc), "heard": heard})

            updates = {
                # Trimmed, because this is evidence for a caregiver deciding
                # whether to ring, not a transcript archive.
                "unclear_replies": trail[-keep:],
                "unclear_count": data.get("unclear_count", 0) + 1,
            }
            transaction.update(ref, updates)
            return {"id": event_id, **data, **updates}

        return apply(self.db.transaction(), self._ref(event_id))

    def confirm_by_caregiver(self, event_id: str, caregiver_id: str) -> dict:
        """Records a dose on the word of the family, not the elder's device.

        Kept distinguishable from the elder confirming it themselves. If this
        record ever reaches a clinician, who said so matters.
        """
        event = self.get_event(event_id)
        if not event:
            raise KeyError(event_id)

        current = MedicationEventStatus(event["status"])
        if current not in CAREGIVER_CONFIRMABLE:
            raise InvalidTransition(current, MedicationEventStatus.TAKEN)

        updates = {
            "status": MedicationEventStatus.TAKEN.value,
            "confirmed_at": datetime.now(timezone.utc),
            "confirmed_by": caregiver_id,
            "confirmed_source": "CAREGIVER",
            "next_attempt_at": None,
        }
        self._ref(event_id).update(updates)
        return {**event, **updates}

    def acknowledge_event(self, event_id: str, caregiver_id: str) -> dict:
        """A caregiver saying "I have got this", which stops the alerts.

        Deliberately separate from confirming the dose: knowing about it is not
        the same as it having been taken, and the record must not blur the two.
        """
        updates = {
            "acknowledged_at": datetime.now(timezone.utc),
            "acknowledged_by": caregiver_id,
            "next_attempt_at": None,
        }
        self._ref(event_id).update(updates)
        return {**(self.get_event(event_id) or {}), **updates}

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

    def cancel_outstanding_for_medication(self, medication_id: str) -> list[str]:
        """Closes any event for a medication that is still expecting an answer.

        Called when a medication is removed. The worker would eventually do
        this too, but only on its next pass, which is a minute away at best and
        never if the scheduler is paused.
        """
        query = self.db.collection(COLLECTION).where(
            filter=firestore.FieldFilter("medication_id", "==", medication_id)
        )

        # Not TERMINAL_STATUSES: an escalated event is terminal for the dose
        # but still has a live ladder chasing the caregiver about a medicine
        # that no longer exists.
        finished = {
            MedicationEventStatus.TAKEN,
            MedicationEventStatus.DECLINED,
            MedicationEventStatus.CANCELLED,
        }

        cancelled = []
        for snapshot in query.stream():
            status = MedicationEventStatus(snapshot.to_dict()["status"])
            if status in finished:
                continue
            self.cancel_event(snapshot.id)
            cancelled.append(snapshot.id)

        return cancelled

    OPEN_STATUSES = frozenset({
        MedicationEventStatus.REMINDER_SENT.value,
        MedicationEventStatus.SNOOZED.value,
    })

    def list_open_events_for_elder(
        self,
        elder_id: str,
        live_within: timedelta | None = None,
        now: datetime | None = None,
    ) -> list[dict]:
        """Every reminder still waiting on an answer, earliest first.

        A morning is rarely one tablet. Returning only the latest hid the rest
        from the elder while they kept counting down towards escalation.

        `live_within` is how long after its scheduled time a dose is still the
        thing the elder is being asked about. Without it a reminder is open
        until something closes it, and the only things that close one are an
        answer from the elder or the worker deciding it is exhausted. A dose
        raised while no phone was paired has neither, so it stayed open for
        ever and was handed to the next device to pair — which then rang about
        eye drops from hours ago the moment it finished pairing. Waiting on a
        worker to tidy up is not an answer either: it does not run while the
        scheduler is paused, and a read this important should not be able to
        return yesterday because a cron job is off.
        """
        now = now or datetime.now(timezone.utc)

        def still_live(event: dict) -> bool:
            if event["status"] not in self.OPEN_STATUSES:
                return False
            if live_within is None:
                return True
            return now < event["scheduled_at"] + live_within

        events = [e for e in self._for_elder(elder_id) if still_live(e)]
        return sorted(events, key=lambda e: e["scheduled_at"])

    def list_events_for_elder_between(
        self,
        elder_id: str,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        events = [
            e for e in self._for_elder(elder_id) if start <= e["scheduled_at"] < end
        ]
        return sorted(events, key=lambda e: e["scheduled_at"])

    def get_active_event_for_elder(
        self,
        elder_id: str,
        live_within: timedelta | None = None,
    ) -> dict | None:
        """The one the elder is asked about first."""
        events = self.list_open_events_for_elder(elder_id, live_within=live_within)
        return events[0] if events else None
