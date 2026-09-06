"""The time the elder is told, and the dose it belongs to.

Both of these were left to the model. It was handed a bare "01:30" with no
instruction anywhere about how to say it, and the time it was handed belonged
to the first dose of the day rather than the one actually ringing.
"""

from datetime import datetime, timedelta
from datetime import timezone as tz
from zoneinfo import ZoneInfo

import pytest

from app.services.medication_event_service import MedicationEventService
from app.services.spoken_time import say_moment, say_time

CAREGIVER = {"X-Caregiver-Id": "caregiver_1"}
KOLKATA = ZoneInfo("Asia/Kolkata")


@pytest.mark.parametrize(
    "hour,minute,expected",
    [
        (1, 30, "1:30 in the morning"),
        (0, 5, "12:05 in the morning"),
        (11, 59, "11:59 in the morning"),
        (12, 0, "12:00 in the afternoon"),
        (16, 45, "4:45 in the afternoon"),
        (17, 0, "5:00 in the evening"),
        (19, 30, "7:30 in the evening"),
        (20, 0, "8:00 at night"),
        (23, 15, "11:15 at night"),
    ],
)
def test_every_hour_lands_in_exactly_one_part_of_the_day(hour, minute, expected):
    """The reported bug was one sentence naming two parts of the day.

    That cannot happen once the phrase is computed: each hour has exactly one
    answer and it is the same one every time.
    """
    assert say_time(hour, minute, "en") == expected


def test_telugu_puts_the_part_of_the_day_first():
    """Word order is not the same in both languages, so the template is not
    either. 1:30 in the morning is ఉదయం 1:30, not 1:30 ఉదయం."""
    assert say_time(1, 30, "te") == "ఉదయం 1:30"
    assert say_time(21, 0, "te") == "రాత్రి 9:00"


def test_a_language_nobody_has_words_for_still_says_something():
    assert say_time(9, 0, "xx") == "9:00 in the morning"
    assert say_time(9, 0, None) == "9:00 in the morning"


def test_the_instant_is_read_in_her_clock_not_in_utc():
    """19:04 UTC is half past midnight in Kolkata, and hers is the only clock
    that matters. Getting this wrong is how a dose moves half a day."""
    moment = datetime(2026, 9, 6, 19, 4, tzinfo=tz.utc)

    assert say_moment(moment, KOLKATA, "en") == "12:34 in the morning"


def _elder(client, name: str, language: str) -> str:
    return client.post(
        "/api/elders",
        json={"name": name, "timezone": "Asia/Kolkata", "preferred_language": language},
        headers=CAREGIVER,
    ).json()["id"]


def test_the_agent_is_told_about_the_dose_that_is_actually_ringing(client, db, monkeypatch):
    """The regression test for the worse of the two bugs.

    scheduled_time came from medication["schedule_time"], which is
    schedule_times[0]. A twice-daily medicine ringing in the evening told the
    model the morning dose - a wrong answer about medication, delivered
    confidently, to the person taking it.
    """
    from app.services import firestore_service as firestore_module
    from app.services import medication_event_service as event_module
    from app.tools import medication_tools

    monkeypatch.setattr(firestore_module, "get_db", lambda: db)
    monkeypatch.setattr(event_module, "get_db", lambda: db)

    elder_id = _elder(client, "Amma", "en")
    medication_id = client.post(
        "/api/medications",
        json={
            "elder_id": elder_id,
            "name": "Amlodipine",
            "dose": "1 tablet",
            "food_instruction": "AFTER_FOOD",
            # Twice a day. The morning one is schedule_times[0].
            "schedule_times": ["08:00", "21:00"],
        },
        headers=CAREGIVER,
    ).json()["id"]

    # The EVENING dose is the one ringing: 21:00 Kolkata is 15:30 UTC.
    evening = datetime.now(tz.utc).replace(hour=15, minute=30, second=0, microsecond=0)
    events = MedicationEventService(db)
    event_id = events.create_event(
        medication_id=medication_id,
        elder_id=elder_id,
        scheduled_at=evening,
        retry_after_minutes=10,
        max_attempts=2,
    )
    events.record_reminder_sent(event_id, evening)

    medication_tools.set_context(
        medication_tools.AgentContext(elder_id=elder_id, event_id=event_id)
    )
    reminder = medication_tools.get_current_reminder()

    assert reminder["success"] is True
    assert reminder["scheduled_time"] == "21:00"
    assert reminder["scheduled_time_spoken"] == "9:00 at night"


def test_the_snooze_reply_is_her_clock_rather_than_a_utc_timestamp(client, db, monkeypatch):
    """It used to return next_attempt_at.isoformat() - a UTC instant, handed to
    the model with no instruction about what to do with it."""
    from app.services import firestore_service as firestore_module
    from app.services import medication_event_service as event_module
    from app.tools import medication_tools

    monkeypatch.setattr(firestore_module, "get_db", lambda: db)
    monkeypatch.setattr(event_module, "get_db", lambda: db)

    elder_id = _elder(client, "Amma", "te")
    medication_id = client.post(
        "/api/medications",
        json={
            "elder_id": elder_id,
            "name": "Amlodipine",
            "dose": "1 tablet",
            "food_instruction": "AFTER_FOOD",
            "schedule_times": ["08:00"],
        },
        headers=CAREGIVER,
    ).json()["id"]

    now = datetime.now(tz.utc)
    events = MedicationEventService(db)
    event_id = events.create_event(
        medication_id=medication_id,
        elder_id=elder_id,
        scheduled_at=now,
        retry_after_minutes=10,
        max_attempts=2,
    )
    events.record_reminder_sent(event_id, now)

    medication_tools.set_context(
        medication_tools.AgentContext(elder_id=elder_id, event_id=event_id)
    )
    snoozed = medication_tools.snooze_reminder(10)

    assert snoozed["success"] is True
    assert "next_reminder_at" not in snoozed
    expected = say_moment(now + timedelta(minutes=10), KOLKATA, "te")
    assert snoozed["next_reminder_spoken"] == expected
