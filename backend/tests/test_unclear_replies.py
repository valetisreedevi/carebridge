"""When CareBridge cannot tell what she meant.

The prompt has always forbidden treating an ambiguous reply as a confirmation.
What it had no way to do was say so: the model simply did not confirm, nothing
was written down, and the household went quiet until the dose escalated. The
elder had answered and nobody heard it.
"""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models.medication_event import MedicationEventStatus
from app.tools import medication_tools

IST = ZoneInfo("Asia/Kolkata")

# Anchored to the day the suite runs, not to the day it was written. The
# dashboard reads the real clock to decide what "today" means, so a fixed date
# here passes once and then quietly fails every day after.
EIGHT_AM_IST = datetime.combine(datetime.now(IST).date(), time(8), IST).astimezone(
    timezone.utc
)


@pytest.fixture
def in_conversation(db, monkeypatch, reminders, seeded):
    """A live reminder, with the tools pointed at the test database."""
    for factory in ("FirestoreService", "MedicationEventService", "NotificationService"):
        original = getattr(medication_tools, factory)
        monkeypatch.setattr(
            medication_tools, factory, lambda _o=original: _o(db)
        )

    result = reminders.run(EIGHT_AM_IST)
    event_id = result["events_created"][0]["event_id"]

    medication_tools.set_context(
        medication_tools.AgentContext(
            elder_id=seeded["elder_id"], event_id=event_id
        )
    )
    return event_id


def _caregiver_alerts(db):
    return [
        d.to_dict()
        for d in db.collection("notifications").stream()
        if d.to_dict().get("audience") == "CAREGIVER"
    ]


def test_the_dose_does_not_move(in_conversation, events):
    """An unintelligible reply is an observation, not a lifecycle stage.

    She has not taken it, refused it, or put it off. Writing this into the
    state machine would mean inventing a state for something that is really
    about the conversation.
    """
    before = events.get_event(in_conversation)["status"]

    medication_tools.report_unclear_reply("mmm the blue one on Tuesday")

    after = events.get_event(in_conversation)
    assert after["status"] == before
    assert after["status"] == MedicationEventStatus.REMINDER_SENT.value


def test_what_she_said_is_kept(in_conversation, events):
    medication_tools.report_unclear_reply("mmm the blue one on Tuesday")

    event = events.get_event(in_conversation)
    assert event["unclear_count"] == 1
    assert event["unclear_replies"][-1]["heard"] == "mmm the blue one on Tuesday"


def test_one_muddled_reply_does_not_summon_the_family(in_conversation, db):
    """A passing lorry is not a reason to ring somebody at work."""
    result = medication_tools.report_unclear_reply("sorry, what?")

    assert result["caregiver_told"] is False
    assert _caregiver_alerts(db) == []


def test_a_second_one_does(in_conversation, db):
    """Two replies nobody could interpret is a person, not a microphone.

    Retrying is the machine's answer and it is the wrong one — at that point
    somebody should be phoning while there is still time.
    """
    medication_tools.report_unclear_reply("sorry, what?")
    result = medication_tools.report_unclear_reply("is it the small one")

    assert result["caregiver_told"] is True

    alerts = _caregiver_alerts(db)
    assert len(alerts) == 1
    assert alerts[0]["reason"] == "NOT_UNDERSTOOD"
    assert "is it the small one" in alerts[0]["message"]
    assert "Nothing has been recorded either way" in alerts[0]["message"]


def test_the_threshold_is_ours_not_the_models(in_conversation, db, monkeypatch):
    """Whether to interrupt somebody is not a turn-by-turn judgement call."""
    from dataclasses import dataclass

    @dataclass
    class MoreForgiving:
        max_unclear_replies: int = 3

    monkeypatch.setattr(medication_tools, "get_settings", MoreForgiving)

    medication_tools.report_unclear_reply("one")
    medication_tools.report_unclear_reply("two")
    assert _caregiver_alerts(db) == []

    medication_tools.report_unclear_reply("three")
    assert len(_caregiver_alerts(db)) == 1


def test_the_trail_is_evidence_not_an_archive(in_conversation, events):
    """Enough for a caregiver to decide whether to ring. Not a transcript."""
    for i in range(8):
        medication_tools.report_unclear_reply(f"reply {i}")

    event = events.get_event(in_conversation)
    assert event["unclear_count"] == 8
    assert len(event["unclear_replies"]) == 5
    assert event["unclear_replies"][0]["heard"] == "reply 3"


def test_an_unclear_reply_shows_up_on_the_day(in_conversation, client, seeded, db):
    """The family should be able to see that she answered and we missed it."""
    from app.api import deps

    medication_tools.report_unclear_reply("the blue one")

    body = client.get(
        f"/api/elders/{seeded['elder_id']}/today",
        headers={"X-Caregiver-Id": seeded["caregiver_id"]},
    ).json()

    rows = [i for i in body["items"] if i["event_id"] == in_conversation]
    assert rows[0]["unclear_count"] == 1
    assert rows[0]["last_unclear"] == "the blue one"
    assert deps  # the client fixture wires the same db these tools wrote to


def test_the_reminder_carries_on_exactly_as_it_would_have(
    in_conversation, reminders, events
):
    """Recording confusion must not rescue the dose from escalating."""
    medication_tools.report_unclear_reply("sorry, what?")

    reminders.run(EIGHT_AM_IST + timedelta(minutes=10))
    final = reminders.run(EIGHT_AM_IST + timedelta(minutes=20))

    assert len(final["escalations"]) == 1
    assert events.get_event(in_conversation)["status"] == (
        MedicationEventStatus.ESCALATED.value
    )
