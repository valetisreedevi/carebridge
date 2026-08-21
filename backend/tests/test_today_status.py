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
