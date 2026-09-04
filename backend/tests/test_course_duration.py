"""A prescription runs for a while and then stops.

Before this, every medication ran forever. A five-day antibiotic and a
lifelong blood-pressure tablet were the same object, and the only thing that
ever ended a course was somebody in the family remembering, on day six, to
open the dashboard and delete it by hand. Nobody remembers on day six.

Two things are worth knowing about these tests:

*   **Every date is anchored to the day the suite runs**, never to a literal.
    Both the worker and the dashboard read the real clock to decide what today
    means, so a fixed date passes once and then starts asserting the wrong
    side of a course boundary a few days later. This is the trap that already
    broke `test_unclear_replies` once.

*   **A medicine with no course fields must behave exactly as it always did.**
    There is live data with neither field, and a default applied on the way in
    would silently end courses nobody set.
"""

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services import course

IST = ZoneInfo("Asia/Kolkata")


def eight_am_ist(day_offset: int = 0):
    """08:00 in Kolkata on a day relative to today, as a UTC instant."""
    day = datetime.now(IST).date() + timedelta(days=day_offset)
    return datetime.combine(day, time(8), IST).astimezone(timezone.utc)


def today_ist():
    return datetime.now(IST).date()


# --- the guard itself -------------------------------------------------------


def test_a_medicine_with_no_course_runs_forever():
    """The old behaviour, which live records still depend on."""
    assert course.runs_on({}, today_ist())
    assert course.runs_on({}, today_ist() + timedelta(days=3650))


def test_a_course_covers_its_first_and_last_day_and_stops_after():
    starts = today_ist()
    medication = {
        "starts_on": starts.isoformat(),
        "ends_on": (starts + timedelta(days=9)).isoformat(),
    }

    assert course.runs_on(medication, starts)
    assert course.runs_on(medication, starts + timedelta(days=9))
    assert not course.runs_on(medication, starts + timedelta(days=10))


def test_a_course_has_not_started_before_its_start_date():
    starts = today_ist() + timedelta(days=2)
    medication = {"starts_on": starts.isoformat()}

    assert not course.runs_on(medication, today_ist())
    assert course.runs_on(medication, starts)


def test_an_unreadable_date_keeps_reminding_rather_than_going_quiet():
    """The safe direction. One extra reminder is an apology; a silent day is
    the thing this product exists to prevent."""
    assert course.runs_on({"ends_on": "not a date"}, today_ist())
    assert course.runs_on({"starts_on": ""}, today_ist())


def test_ten_days_means_ten_days_counted_inclusively():
    starts, ends = course.resolve_window(None, 10, today_ist())
    assert starts == today_ist().isoformat()
    assert ends == (today_ist() + timedelta(days=9)).isoformat()


def test_a_start_with_no_duration_has_no_end():
    starts, ends = course.resolve_window(today_ist(), None, today_ist())
    assert starts == today_ist().isoformat()
    assert ends is None


def test_progress_counts_days_not_doses():
    starts = today_ist() - timedelta(days=3)
    medication = {
        "starts_on": starts.isoformat(),
        "ends_on": (starts + timedelta(days=14)).isoformat(),
    }

    assert course.progress(medication, today_ist()) == {
        "day": 4,
        "of": 15,
        "ends_on": (starts + timedelta(days=14)).isoformat(),
        "finished": False,
    }


def test_an_open_ended_medicine_has_no_progress_to_report():
    assert course.progress({}, today_ist()) is None


# --- the worker -------------------------------------------------------------


@pytest.fixture
def with_course(firestore_service, seeded):
    """Puts a course window on the seeded medicine."""

    def apply(duration_days: int, starts_offset: int = 0):
        starts = today_ist() + timedelta(days=starts_offset)
        starts_on, ends_on = course.resolve_window(starts, duration_days, today_ist())
        firestore_service.update_medication(
            seeded["medication_id"],
            {"starts_on": starts_on, "ends_on": ends_on, "duration_days": duration_days},
        )

    return apply


def test_the_worker_still_reminds_on_the_last_day(reminders, with_course):
    with_course(duration_days=1)

    result = reminders.run(eight_am_ist())

    assert result["events_created"], "the last day of a course is still a day"


def test_the_worker_stops_the_day_after_a_course_ends(reminders, with_course):
    with_course(duration_days=1)

    result = reminders.run(eight_am_ist(day_offset=1))

    assert not result["events_created"]


def test_the_worker_says_nothing_before_a_course_begins(reminders, with_course):
    with_course(duration_days=5, starts_offset=2)

    assert not reminders.run(eight_am_ist())["events_created"]
    assert reminders.run(eight_am_ist(day_offset=2))["events_created"]


# --- the dashboard ----------------------------------------------------------


def test_the_dashboard_agrees_with_the_worker_about_a_finished_course(
    client, firestore_service, seeded
):
    """The two projections of "today" are independent, and a guard on only one
    of them shows the family a dose that will never be reminded."""
    yesterday = today_ist() - timedelta(days=1)
    firestore_service.update_medication(
        seeded["medication_id"],
        {
            "starts_on": (yesterday - timedelta(days=4)).isoformat(),
            "ends_on": yesterday.isoformat(),
            "duration_days": 5,
        },
    )

    response = client.get(
        f"/api/elders/{seeded['elder_id']}/today",
        headers={"X-Caregiver-Id": seeded["caregiver_id"]},
    )

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_the_dashboard_carries_the_course_position(client, firestore_service, seeded):
    starts = today_ist() - timedelta(days=3)
    firestore_service.update_medication(
        seeded["medication_id"],
        {
            "starts_on": starts.isoformat(),
            "ends_on": (starts + timedelta(days=14)).isoformat(),
            "duration_days": 15,
        },
    )

    items = client.get(
        f"/api/elders/{seeded['elder_id']}/today",
        headers={"X-Caregiver-Id": seeded["caregiver_id"]},
    ).json()["items"]

    assert items[0]["course"]["day"] == 4
    assert items[0]["course"]["of"] == 15
    assert items[0]["course"]["finished"] is False


def test_an_open_ended_medicine_carries_no_course_block(client, seeded):
    items = client.get(
        f"/api/elders/{seeded['elder_id']}/today",
        headers={"X-Caregiver-Id": seeded["caregiver_id"]},
    ).json()["items"]

    assert items[0]["course"] is None


# --- the routes -------------------------------------------------------------


def test_creating_a_ten_day_course_stores_its_end(client, seeded):
    """The end is settled on the way in, so the per-minute worker never has to
    work it out again."""
    response = client.post(
        "/api/medications",
        headers={"X-Caregiver-Id": seeded["caregiver_id"]},
        json={
            "elder_id": seeded["elder_id"],
            "name": "Azithromycin",
            "dose": "1 tablet",
            "food_instruction": "AFTER_FOOD",
            "schedule_times": ["08:00", "20:00"],
            "duration_days": 10,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["starts_on"] == today_ist().isoformat()
    assert body["ends_on"] == (today_ist() + timedelta(days=9)).isoformat()
    # And the second dose of the day survived the trip, which it did not
    # before the form could hold more than one time.
    assert body["schedule_times"] == ["08:00", "20:00"]


def test_moving_a_course_back_to_ongoing_clears_the_end(client, seeded):
    """Zero has to be a real value: `exclude_none` would drop a null and leave
    the old end date quietly in place."""
    created = client.post(
        "/api/medications",
        headers={"X-Caregiver-Id": seeded["caregiver_id"]},
        json={
            "elder_id": seeded["elder_id"],
            "name": "Azithromycin",
            "dose": "1 tablet",
            "food_instruction": "AFTER_FOOD",
            "schedule_times": ["08:00"],
            "duration_days": 10,
        },
    ).json()

    updated = client.put(
        f"/api/medications/{created['id']}",
        headers={"X-Caregiver-Id": seeded["caregiver_id"]},
        json={"duration_days": 0},
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["ends_on"] is None
