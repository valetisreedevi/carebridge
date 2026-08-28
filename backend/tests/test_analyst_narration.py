"""The analyst is allowed to be slow, wrong, or entirely absent.

This is the whole argument for putting a second model in a system that must not
depend on one. It runs after the decision is made and after the first alert has
already gone out, so the worst thing a failure can do is leave the wording
plain — which is what these tests assert, one failure mode at a time.

The tests that need the analyst opt back in explicitly; conftest switches it off
everywhere else.
"""

from datetime import timedelta

import pytest

from tests.test_reminder_worker import EIGHT_AM_IST

CAREGIVER = {"X-Caregiver-Id": "caregiver_1"}


@pytest.fixture
def analyst(monkeypatch):
    """A stand-in analyst whose behaviour each test chooses."""

    class Stub:
        wording: str | None = "Amma has missed this evening tablet three times."
        calls: list = []

        def __init__(self, *args, **kwargs):
            pass

        def narrate_blocking(self, kind, brief, key):
            Stub.calls.append((kind, key, brief))
            if isinstance(Stub.wording, Exception):
                raise Stub.wording
            return Stub.wording

        async def narrate(self, kind, brief, key):
            return self.narrate_blocking(kind, brief, key)

    Stub.calls = []

    from app.services import narration_service

    monkeypatch.setattr(narration_service, "NarrationService", Stub)
    return Stub


def _escalated(reminders, db):
    """Drives one dose to escalation and returns the caregiver dispatches."""
    reminders.run(EIGHT_AM_IST)
    reminders.run(EIGHT_AM_IST + timedelta(minutes=10))
    reminders.run(EIGHT_AM_IST + timedelta(minutes=20))
    return reminders


def _caregiver_messages(db):
    return [
        (d.to_dict().get("channel"), d.to_dict().get("message"))
        for d in db.collection("notifications").stream()
        if d.to_dict().get("audience") == "CAREGIVER"
    ]


def test_the_first_alert_never_waits_for_the_model(analyst, reminders, db, seeded):
    """The push carries the sentence this codebase wrote, always.

    Whatever the analyst is doing, the fast channel has already left. That is
    the property that lets a model exist anywhere near an escalation path.
    """
    _escalated(reminders, db)

    channel, message = _caregiver_messages(db)[0]
    assert channel == "push"
    assert "has not confirmed" in message
    assert analyst.calls == []


def test_the_slower_channel_carries_the_better_wording(
    analyst, reminders, db, seeded
):
    _escalated(reminders, db)
    reminders.run(EIGHT_AM_IST + timedelta(minutes=30))

    messages = _caregiver_messages(db)
    assert messages[1][0] == "email"
    assert messages[1][1] == "Amma has missed this evening tablet three times."

    kind, _, brief = analyst.calls[0]
    assert kind == "escalation"
    # It is handed facts, not asked to find them.
    assert brief["reminder_attempts"] == 2
    assert brief["reached_a_phone"] is True
    assert "same_dose_last_14_days" in brief


def test_a_failing_analyst_changes_nothing(analyst, reminders, db, seeded):
    analyst.wording = RuntimeError("Vertex is having an afternoon")

    _escalated(reminders, db)
    reminders.run(EIGHT_AM_IST + timedelta(minutes=30))

    channel, message = _caregiver_messages(db)[1]
    assert channel == "email"
    assert "has not confirmed" in message


def test_a_silent_analyst_changes_nothing(analyst, reminders, db, seeded):
    analyst.wording = None

    _escalated(reminders, db)
    reminders.run(EIGHT_AM_IST + timedelta(minutes=30))

    assert "has not confirmed" in _caregiver_messages(db)[1][1]


def test_wording_is_generated_once_and_reused(analyst, reminders, db, seeded, events):
    """A third rung says what the second one said.

    Somebody being chased about the same dose through three channels must not
    receive three differently worded accounts of it.
    """
    _escalated(reminders, db)
    reminders.run(EIGHT_AM_IST + timedelta(minutes=30))
    reminders.run(EIGHT_AM_IST + timedelta(minutes=60))

    assert len(analyst.calls) == 1


def test_an_undelivered_dose_is_briefed_as_ours_to_fix(
    analyst, reminders, db, firestore_service, seeded
):
    """The brief must not let a model blur plumbing into behaviour."""
    for device in db.collection("devices").stream():
        db.collection("devices").document(device.id).update({"active": False})

    _escalated(reminders, db)
    reminders.run(EIGHT_AM_IST + timedelta(minutes=30))

    _, _, brief = analyst.calls[0]
    assert brief["reached_a_phone"] is False
    assert brief["reason"] == "UNREACHABLE"


def test_the_weekly_note_is_written_without_a_model_when_there_is_none(
    client, seeded
):
    """The weekly note is a feature of CareBridge, not of Gemini being up."""
    body = client.get(
        f"/api/elders/{seeded['elder_id']}/insight", headers=CAREGIVER
    ).json()

    assert body["narrated"] is False
    assert body["note"] == body["plain_note"]
    assert body["note"]


def test_the_weekly_note_reports_a_quiet_week_as_quiet(client, seeded):
    """Asked to compare two weeks a model always finds something to say.

    Arithmetic is willing to report that nothing changed, which is why the
    comparison is not the model's job.
    """
    body = client.get(
        f"/api/elders/{seeded['elder_id']}/insight", headers=CAREGIVER
    ).json()

    assert body["what_changed"] == []


def test_the_weekly_note_never_blames_her_for_a_phone_nobody_set_up(seeded):
    """The sentence that separates our failure from her behaviour.

    Written against the note directly rather than through a week window, so it
    asserts the wording rule itself and not what day the suite happens to run.
    """
    from app.services.adherence_service import plain_weekly_note

    note = plain_weekly_note({
        "elder_name": "Amma",
        "this_week": {
            "scheduled": 7,
            "asked": 5,
            "taken": 5,
            "unreachable": 2,
            "taken_on_trust": 0,
        },
        "what_changed": [],
    })

    assert "5 of the 5 doses" in note
    assert "2 doses were never asked about" in note
    assert "no reminder reached the phone" in note
    # Nothing in the sentence implies she ignored anything.
    assert "missed" not in note


def test_the_weekly_note_says_when_the_family_recorded_the_dose(seeded):
    from app.services.adherence_service import plain_weekly_note

    note = plain_weekly_note({
        "elder_name": "Amma",
        "this_week": {
            "scheduled": 4,
            "asked": 4,
            "taken": 4,
            "unreachable": 0,
            "taken_on_trust": 3,
        },
        "what_changed": [],
    })

    assert "3 of those were recorded by the family rather than by Amma" in note


def test_the_weekly_note_leads_with_lateness_when_that_is_what_moved(seeded):
    """Latency is the number that moves before a dose is ever missed."""
    from app.services.adherence_service import plain_weekly_note

    note = plain_weekly_note({
        "elder_name": "Amma",
        "this_week": {
            "scheduled": 7,
            "asked": 7,
            "taken": 7,
            "unreachable": 0,
            "taken_on_trust": 0,
        },
        "what_changed": [{
            "metric": "median_minutes_to_taken",
            "now": 48.0,
            "usual": 9.0,
            "direction": "worse",
        }],
    })

    assert "later than usual" in note
