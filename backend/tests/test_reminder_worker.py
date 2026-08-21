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


def test_a_dose_hours_past_its_time_is_not_raised(reminders):
    """A stale dose stays quiet: a late "take it now" invites a double dose."""
    created = reminders.materialise_due_events(EIGHT_AM_IST + timedelta(hours=4))

    assert created == []


def test_a_dose_within_the_stale_window_is_still_raised(reminders, seeded):
    created = reminders.materialise_due_events(EIGHT_AM_IST + timedelta(minutes=90))

    assert len(created) == 1
    assert created[0]["medication_id"] == seeded["medication_id"]


def test_removing_a_medication_stops_reminders_already_in_flight(reminders, seeded):
    """Remove must mean remove.

    The schedule stops producing new events, but an event created before the
    removal still had a live next_attempt_at, so the worker kept reminding and
    would eventually escalate a medicine the caregiver had deleted.
    """
    first = reminders.run(EIGHT_AM_IST)
    assert len(first["reminders_sent"]) == 1

    reminders.firestore.delete_medication(seeded["medication_id"])

    after = reminders.run(EIGHT_AM_IST + timedelta(minutes=10))

    assert after["reminders_sent"] == []
    assert after["escalations"] == []


def test_removing_a_medication_cancels_its_outstanding_event(reminders, seeded):
    result = reminders.run(EIGHT_AM_IST)
    event_id = result["events_created"][0]["event_id"]

    reminders.firestore.delete_medication(seeded["medication_id"])
    reminders.run(EIGHT_AM_IST + timedelta(minutes=10))

    event = reminders.events.get_event(event_id)
    assert event["status"] == MedicationEventStatus.CANCELLED.value


def test_a_snooze_still_earns_another_reminder(reminders, seeded):
    """The exemption is deliberate: a snooze is an answer, not silence."""
    result = reminders.run(EIGHT_AM_IST)
    event_id = result["events_created"][0]["event_id"]

    reminders.events.snooze_event(event_id, minutes=10, now=EIGHT_AM_IST)
    after = reminders.run(EIGHT_AM_IST + timedelta(minutes=10))

    assert len(after["reminders_sent"]) == 1
    assert after["escalations"] == []


def test_snoozing_forever_eventually_tells_the_caregiver(reminders, seeded):
    """The person putting a dose off all morning is the one to worry about."""
    result = reminders.run(EIGHT_AM_IST)
    event_id = result["events_created"][0]["event_id"]

    at = EIGHT_AM_IST
    for _ in range(3):
        reminders.events.snooze_event(event_id, minutes=10, now=at)
        at += timedelta(minutes=10)
        final = reminders.run(at)

    # The third snooze reaches the ceiling, so that pass escalates instead of
    # sending a fourth reminder.
    assert len(final["escalations"]) == 1
    assert "put off" in final["escalations"][0]["message"]
    assert "not taken" in final["escalations"][0]["message"]


def test_a_dose_snoozed_past_the_cutoff_escalates_on_time(reminders, seeded):
    """Even within the snooze allowance, a dose gets too late to keep waiting."""
    result = reminders.run(EIGHT_AM_IST)
    event_id = result["events_created"][0]["event_id"]

    late = EIGHT_AM_IST + timedelta(minutes=95)
    reminders.events.snooze_event(event_id, minutes=1, now=late)
    final = reminders.run(late + timedelta(minutes=1))

    assert len(final["escalations"]) == 1


def test_silence_is_still_worded_as_not_confirmed(reminders, seeded):
    """Never "not taken": the system does not know that, and it starts a row."""
    reminders.run(EIGHT_AM_IST)
    reminders.run(EIGHT_AM_IST + timedelta(minutes=10))
    final = reminders.run(EIGHT_AM_IST + timedelta(minutes=20))

    assert "has not confirmed" in final["escalations"][0]["message"]


def test_several_tablets_at_once_ring_the_phone_only_once(reminders, firestore_service, seeded):
    """Three alerts for one breakfast is how a phone gets ignored."""
    for name in ("Metformin", "Vitamin D"):
        firestore_service.create_medication({
            "elder_id": seeded["elder_id"],
            "name": name,
            "dose": "1 tablet",
            "food_instruction": "AFTER_FOOD",
            "schedule_times": ["08:00"],
            "schedule_time": "08:00",
            "retry_after_minutes": 10,
            "max_attempts": 2,
        })

    result = reminders.run(EIGHT_AM_IST)

    assert len(result["reminders_sent"]) == 3, "every dose still counts as reminded"
    assert [r["alerted"] for r in result["reminders_sent"]].count(True) == 1


def test_each_tablet_in_a_batch_escalates_on_its_own(reminders, firestore_service, seeded):
    """Taking two of three must not silence the third."""
    firestore_service.create_medication({
        "elder_id": seeded["elder_id"],
        "name": "Metformin",
        "dose": "1 tablet",
        "food_instruction": "AFTER_FOOD",
        "schedule_times": ["08:00"],
        "schedule_time": "08:00",
        "retry_after_minutes": 10,
        "max_attempts": 2,
    })

    created = reminders.run(EIGHT_AM_IST)["events_created"]
    reminders.events.confirm_event(created[0]["event_id"])

    reminders.run(EIGHT_AM_IST + timedelta(minutes=10))
    final = reminders.run(EIGHT_AM_IST + timedelta(minutes=20))

    assert len(final["escalations"]) == 1
    assert final["escalations"][0]["event_id"] == created[1]["event_id"]
