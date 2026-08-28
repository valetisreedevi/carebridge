"""How the dashboard describes a scheduled time that never became an event."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.api.elders import _unmaterialised_status

IST = ZoneInfo("Asia/Kolkata")
NOON = datetime(2026, 8, 20, 12, 0, tzinfo=IST)


def test_a_time_still_to_come_is_upcoming():
    assert _unmaterialised_status("18:30", NOON) == "UPCOMING"


def test_a_time_that_passed_hours_ago_is_missed():
    """The bug this replaces: 07:00 read "Later today" at noon."""
    assert _unmaterialised_status("07:00", NOON) == "MISSED"


def test_a_time_that_passed_seconds_ago_is_still_upcoming():
    """The worker runs once a minute, so it has not had its turn yet."""
    assert _unmaterialised_status("11:59", NOON) == "UPCOMING"


def test_a_time_past_the_grace_window_is_missed():
    assert _unmaterialised_status("11:55", NOON) == "MISSED"


def test_an_unreadable_time_does_not_crash_the_dashboard():
    assert _unmaterialised_status("not-a-time", NOON) == "UPCOMING"


def test_the_day_reports_three_numbers_that_add_up(client, seeded):
    """The headline a family can check rather than trust.

    Almost every product in this category shows one number — taken over
    scheduled — which turns a phone nobody set up into a person ignoring their
    tablets. These three keep reach and outcome apart, and the reach half is a
    partition, so it always balances.
    """
    body = client.get(
        f"/api/elders/{seeded['elder_id']}/today",
        headers={"X-Caregiver-Id": seeded["caregiver_id"]},
    ).json()

    ledger = body["ledger"]
    assert ledger["scheduled"] == (
        ledger["asked"] + ledger["unreachable"] + ledger["not_yet_due"]
    )
    assert ledger["scheduled"] == len(body["items"])


def test_a_time_the_worker_never_reached_is_not_counted_as_asked(client, seeded):
    """A paused scheduler must not read as a person ignoring their tablets.

    No event was ever created for the time, so nothing was delivered. That is
    ours, and the denominator has to say so rather than quietly shrinking.
    """
    body = client.get(
        f"/api/elders/{seeded['elder_id']}/today",
        headers={"X-Caregiver-Id": seeded["caregiver_id"]},
    ).json()

    missed = [i for i in body["items"] if i["status"] == "MISSED"]
    if missed:
        assert body["ledger"]["unreachable"] >= len(missed)
        assert body["ledger"]["asked"] == 0
