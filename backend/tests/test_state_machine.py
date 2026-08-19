from datetime import datetime, timedelta, timezone

import pytest

from app.models.medication_event import (
    InvalidTransition,
    MedicationEventStatus,
    can_transition,
)


@pytest.fixture
def event_id(events, seeded):
    return events.create_event(
        medication_id=seeded["medication_id"],
        elder_id=seeded["elder_id"],
        scheduled_at=datetime.now(timezone.utc),
        retry_after_minutes=10,
        max_attempts=2,
    )


def test_new_event_is_pending_and_polls_at_its_scheduled_time(events, event_id):
    event = events.get_event(event_id)

    assert event["status"] == MedicationEventStatus.PENDING.value
    assert event["attempt"] == 0
    assert event["next_attempt_at"] == event["scheduled_at"]


def test_reminder_increments_attempt_and_schedules_the_retry(events, event_id):
    updated = events.record_reminder_sent(event_id)

    assert updated["status"] == MedicationEventStatus.REMINDER_SENT.value
    assert updated["attempt"] == 1

    gap = updated["next_attempt_at"] - updated["last_attempt_at"]
    assert gap == timedelta(minutes=10)


def test_confirming_stops_the_worker_from_seeing_the_event(events, event_id):
    events.record_reminder_sent(event_id)
    confirmed = events.confirm_event(event_id)

    assert confirmed["status"] == MedicationEventStatus.TAKEN.value
    assert confirmed["confirmed_at"] is not None
    assert confirmed["next_attempt_at"] is None

    far_future = datetime.now(timezone.utc) + timedelta(days=1)
    assert events.get_due_events(far_future) == []


def test_snooze_moves_the_next_attempt_without_burning_an_attempt(events, event_id):
    events.record_reminder_sent(event_id)
    before = events.get_event(event_id)["attempt"]

    snoozed = events.snooze_event(event_id, 10)

    assert snoozed["status"] == MedicationEventStatus.SNOOZED.value
    assert snoozed["attempt"] == before
    assert snoozed["next_attempt_at"] > datetime.now(timezone.utc)


def test_declining_is_terminal_and_records_the_reason(events, event_id):
    events.record_reminder_sent(event_id)
    declined = events.decline_event(event_id, "feeling unwell")

    assert declined["status"] == MedicationEventStatus.DECLINED.value
    assert declined["decline_reason"] == "feeling unwell"

    with pytest.raises(InvalidTransition):
        events.confirm_event(event_id)


def test_a_confirmed_event_cannot_be_reopened(events, event_id):
    events.record_reminder_sent(event_id)
    events.confirm_event(event_id)

    for action in (
        lambda: events.confirm_event(event_id),
        lambda: events.snooze_event(event_id, 5),
        lambda: events.escalate_event(event_id),
        lambda: events.decline_event(event_id, "changed my mind"),
    ):
        with pytest.raises(InvalidTransition):
            action()


def test_pending_events_cannot_jump_straight_to_taken(events, event_id):
    with pytest.raises(InvalidTransition):
        events.confirm_event(event_id)


def test_every_terminal_status_is_a_dead_end():
    terminal = [
        MedicationEventStatus.TAKEN,
        MedicationEventStatus.DECLINED,
        MedicationEventStatus.ESCALATED,
        MedicationEventStatus.CANCELLED,
    ]

    for status in terminal:
        for target in MedicationEventStatus:
            assert not can_transition(status, target)
