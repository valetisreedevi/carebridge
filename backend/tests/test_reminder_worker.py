from datetime import datetime, timedelta, timezone

from app.models.medication_event import MedicationEventStatus

# 08:00 in Asia/Kolkata is 02:30 UTC.
EIGHT_AM_IST = datetime(2026, 8, 19, 2, 30, tzinfo=timezone.utc)


def test_schedule_becomes_an_event_at_the_elders_local_time(reminders, seeded):
    created = reminders.materialise_due_events(EIGHT_AM_IST)

    assert len(created) == 1
    assert created[0]["medication_id"] == seeded["medication_id"]

    event = reminders.events.get_event(created[0]["event_id"])
    assert event["scheduled_at"] == EIGHT_AM_IST


def test_nothing_is_created_before_the_scheduled_time(reminders):
    assert reminders.materialise_due_events(EIGHT_AM_IST - timedelta(hours=2)) == []


def test_running_the_worker_twice_a_minute_apart_creates_one_event(reminders):
    reminders.materialise_due_events(EIGHT_AM_IST)
    second_pass = reminders.materialise_due_events(EIGHT_AM_IST + timedelta(minutes=1))

    assert second_pass == []


def test_silence_produces_two_reminders_then_an_escalation(reminders, db, seeded):
    result = reminders.run(EIGHT_AM_IST)
    event_id = result["events_created"][0]["event_id"]

    assert len(result["reminders_sent"]) == 1
    assert result["reminders_sent"][0]["attempt"] == 1

    second = reminders.run(EIGHT_AM_IST + timedelta(minutes=10))
    assert len(second["reminders_sent"]) == 1
    assert second["reminders_sent"][0]["attempt"] == 2
    assert second["escalations"] == []

    third = reminders.run(EIGHT_AM_IST + timedelta(minutes=20))
    assert third["reminders_sent"] == []
    assert len(third["escalations"]) == 1

    assert (
        reminders.events.get_event(event_id)["status"]
        == MedicationEventStatus.ESCALATED.value
    )


def test_escalation_says_not_confirmed_rather_than_not_taken(reminders, seeded):
    reminders.run(EIGHT_AM_IST)
    reminders.run(EIGHT_AM_IST + timedelta(minutes=10))
    result = reminders.run(EIGHT_AM_IST + timedelta(minutes=20))

    message = result["escalations"][0]["message"]

    assert "has not confirmed" in message
    assert "not taken" not in message.lower()
    assert "Amma" in message and "Amlodipine" in message


def test_the_caregiver_alert_is_addressed_to_the_right_caregiver(
    reminders, notifications, seeded
):
    reminders.run(EIGHT_AM_IST)
    reminders.run(EIGHT_AM_IST + timedelta(minutes=10))
    reminders.run(EIGHT_AM_IST + timedelta(minutes=20))

    alerts = notifications.list_for_caregiver(seeded["caregiver_id"])

    assert len(alerts) == 1
    assert alerts[0]["reason"] == "NOT_CONFIRMED"
    assert notifications.list_for_caregiver("someone_else") == []


def test_confirming_after_the_first_reminder_prevents_escalation(reminders, seeded):
    result = reminders.run(EIGHT_AM_IST)
    event_id = result["events_created"][0]["event_id"]

    reminders.events.confirm_event(event_id)

    later = reminders.run(EIGHT_AM_IST + timedelta(minutes=30))

    assert later["reminders_sent"] == []
    assert later["escalations"] == []


def test_a_snooze_earns_another_reminder_even_at_the_attempt_limit(reminders, seeded):
    result = reminders.run(EIGHT_AM_IST)
    event_id = result["events_created"][0]["event_id"]

    reminders.run(EIGHT_AM_IST + timedelta(minutes=10))
    assert reminders.events.get_event(event_id)["attempt"] == 2

    reminders.events.snooze_event(event_id, 10, EIGHT_AM_IST + timedelta(minutes=12))
    after_snooze = reminders.run(EIGHT_AM_IST + timedelta(minutes=25))

    assert len(after_snooze["reminders_sent"]) == 1
    assert after_snooze["escalations"] == []


def test_the_worker_ignores_events_whose_medication_was_deleted(
    reminders, firestore_service, seeded
):
    reminders.materialise_due_events(EIGHT_AM_IST)
    db_events = reminders.events.get_due_events(EIGHT_AM_IST)
    event_id = db_events[0]["id"]

    reminders.db.raw("medications").pop(seeded["medication_id"])

    result = reminders.process_due_events(EIGHT_AM_IST)

    assert result["reminders_sent"] == []
    assert (
        reminders.events.get_event(event_id)["status"]
        == MedicationEventStatus.CANCELLED.value
    )
