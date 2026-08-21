"""Reaching the caregiver when the first attempt goes nowhere.

Push fails closed and silently: no granted permission means the alert is a row
in the database that only somebody already looking at the dashboard will see.
The one moment CareBridge exists for cannot be the one with no delivery.
"""

from datetime import timedelta

from app.models.medication_event import MedicationEventStatus

EIGHT_AM_IST = __import__("tests.test_reminder_worker", fromlist=["x"]).EIGHT_AM_IST


def _escalated(reminders, seeded):
    """Runs a dose all the way to escalation and returns its event."""
    result = reminders.run(EIGHT_AM_IST)
    event_id = result["events_created"][0]["event_id"]

    reminders.run(EIGHT_AM_IST + timedelta(minutes=10))
    final = reminders.run(EIGHT_AM_IST + timedelta(minutes=20))

    assert len(final["escalations"]) == 1
    return event_id, final["escalations"][0]


def test_the_first_attempt_is_a_push(reminders, seeded):
    _, escalation = _escalated(reminders, seeded)

    assert escalation["channel"] == "push"


def test_an_unanswered_push_is_followed_by_email(reminders, db, seeded):
    event_id, _ = _escalated(reminders, seeded)

    later = EIGHT_AM_IST + timedelta(minutes=30)
    followed = reminders.run(later)

    assert len(followed["escalations"]) == 1
    assert followed["escalations"][0]["channel"] == "email"

    dispatches = [
        d.to_dict() for d in db.collection("notifications").stream()
    ]
    channels = [d.get("channel") for d in dispatches if d.get("audience") == "CAREGIVER"]
    assert channels == ["push", "email"]


def test_the_ladder_stops_once_the_caregiver_says_they_have_it(
    reminders, events, seeded
):
    event_id, _ = _escalated(reminders, seeded)

    events.acknowledge_event(event_id, "caregiver_1")
    followed = reminders.run(EIGHT_AM_IST + timedelta(minutes=30))

    assert followed["escalations"] == []


def test_the_ladder_stops_when_it_runs_out_of_channels(reminders, events, seeded):
    """Two channels means two tries, not an endless drip."""
    event_id, _ = _escalated(reminders, seeded)

    reminders.run(EIGHT_AM_IST + timedelta(minutes=30))
    after_last = reminders.run(EIGHT_AM_IST + timedelta(minutes=60))

    assert after_last["escalations"] == []
    assert events.get_event(event_id)["next_attempt_at"] is None


def test_acknowledging_does_not_claim_the_dose_was_taken(reminders, events, seeded):
    """Knowing about it and it having been swallowed are different facts."""
    event_id, _ = _escalated(reminders, seeded)

    events.acknowledge_event(event_id, "caregiver_1")
    event = events.get_event(event_id)

    assert event["status"] == MedicationEventStatus.ESCALATED.value
    assert event["acknowledged_by"] == "caregiver_1"
    assert event.get("confirmed_at") is None


def test_the_follow_up_repeats_the_original_wording(reminders, seeded):
    """The second message must not contradict the first."""
    _, first = _escalated(reminders, seeded)

    followed = reminders.run(EIGHT_AM_IST + timedelta(minutes=30))

    assert followed["escalations"][0]["message"] == first["message"]


def test_removing_a_medication_stops_a_running_ladder(reminders, seeded):
    """The ladder keeps an escalated event live, so removal has to close it.

    Without this the worker tries to cancel an event it is not allowed to
    cancel, and the whole run dies on an illegal transition.
    """
    event_id, _ = _escalated(reminders, seeded)

    reminders.firestore.delete_medication(seeded["medication_id"])
    followed = reminders.run(EIGHT_AM_IST + timedelta(minutes=30))

    assert followed["escalations"] == []
    assert reminders.events.get_event(event_id)["next_attempt_at"] is None
