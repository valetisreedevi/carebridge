"""Moving a dose must not leave the old one still ringing.

Deleting a medication has always closed its outstanding events, because a
reminder for a medicine that no longer exists keeps chasing a family about a
dose nobody has to take. Rescheduling is the same act by another name, and it
did not: the old time kept its live event while the worker raised a second one
for the new time, so one tablet produced two reminders and an escalation about
a dose that had moved.
"""

from datetime import datetime, timezone as tz

from app.models.medication_event import MedicationEventStatus
from app.services.medication_event_service import MedicationEventService

CAREGIVER = {"X-Caregiver-Id": "caregiver_1"}


def _household(client, times: list[str]) -> tuple[str, str]:
    elder_id = client.post(
        "/api/elders",
        json={"name": "Amma", "timezone": "Asia/Kolkata"},
        headers=CAREGIVER,
    ).json()["id"]

    medication_id = client.post(
        "/api/medications",
        json={
            "elder_id": elder_id,
            "name": "Amlodipine",
            "dose": "1 tablet",
            "food_instruction": "AFTER_FOOD",
            "schedule_times": times,
        },
        headers=CAREGIVER,
    ).json()["id"]

    return elder_id, medication_id


def _live_event(db, elder_id: str, medication_id: str) -> str:
    events = MedicationEventService(db)
    event_id = events.create_event(
        medication_id=medication_id,
        elder_id=elder_id,
        scheduled_at=datetime.now(tz.utc),
        retry_after_minutes=10,
        max_attempts=2,
    )
    events.record_reminder_sent(event_id, datetime.now(tz.utc))
    return event_id


def _status(db, event_id: str) -> str:
    return MedicationEventService(db).get_event(event_id)["status"]


def test_moving_the_time_closes_the_reminder_still_waiting_on_the_old_one(
    client, db
):
    elder_id, medication_id = _household(client, ["08:00"])
    event_id = _live_event(db, elder_id, medication_id)

    client.put(
        f"/api/medications/{medication_id}",
        json={"schedule_times": ["09:30"]},
        headers=CAREGIVER,
    )

    assert _status(db, event_id) == MedicationEventStatus.CANCELLED.value


def test_editing_the_dose_leaves_a_reminder_in_progress_alone(client, db):
    """She may be part-way through answering it. Only the time moving is a
    reason to take the question away from her."""
    elder_id, medication_id = _household(client, ["08:00"])
    event_id = _live_event(db, elder_id, medication_id)

    client.put(
        f"/api/medications/{medication_id}",
        json={"dose": "2 tablets"},
        headers=CAREGIVER,
    )

    assert _status(db, event_id) == MedicationEventStatus.REMINDER_SENT.value


def test_saving_the_same_times_again_is_not_a_reschedule(client, db):
    """The edit form submits every field, so an unchanged schedule arrives on
    the wire looking exactly like a changed one."""
    elder_id, medication_id = _household(client, ["08:00"])
    event_id = _live_event(db, elder_id, medication_id)

    client.put(
        f"/api/medications/{medication_id}",
        json={"schedule_times": ["08:00"], "dose": "1 tablet"},
        headers=CAREGIVER,
    )

    assert _status(db, event_id) == MedicationEventStatus.REMINDER_SENT.value


def test_a_dose_already_taken_is_never_reopened_or_cancelled(client, db):
    """Rescheduling changes what happens next, not what already happened."""
    elder_id, medication_id = _household(client, ["08:00"])
    event_id = _live_event(db, elder_id, medication_id)
    MedicationEventService(db).confirm_event(event_id)

    client.put(
        f"/api/medications/{medication_id}",
        json={"schedule_times": ["09:30"]},
        headers=CAREGIVER,
    )

    assert _status(db, event_id) == MedicationEventStatus.TAKEN.value
