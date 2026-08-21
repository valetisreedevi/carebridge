"""Telling a family nobody answered, when nobody was ever asked.

send_reminder returns how many phones it reached. The worker ignored it, ran
the full attempt count against a household with no phone set up, and then told
the family she "has not confirmed" - which reads as a person ignoring her
tablets. It is the exact misunderstanding CareBridge exists to remove, and the
product was manufacturing it.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.models.medication_event import MedicationEventStatus

EIGHT_AM_IST = datetime(2026, 8, 21, 2, 30, tzinfo=timezone.utc)


@pytest.fixture
def household(firestore_service):
    """An elder with an 08:00 dose and, deliberately, no phone."""
    firestore_service.upsert_caregiver("caregiver_1", email="family@example.test")
    elder_id = firestore_service.create_elder(
        name="Amma", caregiver_id="caregiver_1", elder_timezone="Asia/Kolkata"
    )
    medication_id = firestore_service.create_medication({
        "elder_id": elder_id,
        "name": "Amlodipine",
        "dose": "1 tablet",
        "food_instruction": "BEFORE_FOOD",
        "schedule_times": ["08:00"],
        "schedule_time": "08:00",
        "retry_after_minutes": 10,
        "max_attempts": 2,
    })
    return {"elder_id": elder_id, "medication_id": medication_id}


def _run_to_escalation(reminders):
    reminders.run(EIGHT_AM_IST)
    reminders.run(EIGHT_AM_IST + timedelta(minutes=10))
    return reminders.run(EIGHT_AM_IST + timedelta(minutes=20))


# ---------------- with nowhere to send ----------------


def test_an_undelivered_reminder_is_recorded_as_undelivered(reminders, household):
    result = reminders.run(EIGHT_AM_IST)

    assert result["reminders_sent"][0]["reached_a_phone"] is False


def test_the_family_is_told_the_phone_could_not_be_reached(reminders, household):
    final = _run_to_escalation(reminders)

    assert final["escalations"][0]["reason"] == "UNREACHABLE"


def test_the_message_does_not_blame_her(reminders, household):
    final = _run_to_escalation(reminders)
    message = final["escalations"][0]["message"]

    assert "could not reach" in message
    assert "Amma" in message
    assert "has not confirmed" not in message
    assert "has not taken" not in message


def test_the_message_says_what_to_do_about_it(reminders, household):
    final = _run_to_escalation(reminders)

    assert "set up" in final["escalations"][0]["message"]


def test_a_later_rung_keeps_the_same_explanation(reminders, db, household):
    _run_to_escalation(reminders)
    followed = reminders.run(EIGHT_AM_IST + timedelta(minutes=30))

    assert followed["escalations"][0]["reason"] == "UNREACHABLE"
    assert "could not reach" in followed["escalations"][0]["message"]


# ---------------- with a phone paired ----------------


def test_a_reminder_that_reached_a_phone_says_so(
    reminders, firestore_service, household
):
    firestore_service.register_device(household["elder_id"], "fcm-token-on-the-phone")

    result = reminders.run(EIGHT_AM_IST)

    assert result["reminders_sent"][0]["reached_a_phone"] is True


def test_she_is_described_as_not_confirming_only_when_asked(
    reminders, firestore_service, household
):
    firestore_service.register_device(household["elder_id"], "fcm-token-on-the-phone")

    final = _run_to_escalation(reminders)

    assert final["escalations"][0]["reason"] == "NOT_CONFIRMED"
    assert "has not confirmed" in final["escalations"][0]["message"]


def test_pairing_part_way_through_counts_as_reached(
    reminders, firestore_service, household
):
    """One delivered reminder means she was genuinely asked."""
    reminders.run(EIGHT_AM_IST)
    firestore_service.register_device(household["elder_id"], "fcm-token-on-the-phone")
    reminders.run(EIGHT_AM_IST + timedelta(minutes=10))

    final = reminders.run(EIGHT_AM_IST + timedelta(minutes=20))

    assert final["escalations"][0]["reason"] == "NOT_CONFIRMED"


def test_a_shared_phone_counts_for_every_dose_in_the_batch(
    reminders, firestore_service, household
):
    """Only the first dose of a batch pushes; the rest must not read that as
    having no phone."""
    firestore_service.create_medication({
        "elder_id": household["elder_id"],
        "name": "Metformin",
        "dose": "1 tablet",
        "food_instruction": "AFTER_FOOD",
        "schedule_times": ["08:00"],
        "schedule_time": "08:00",
        "retry_after_minutes": 10,
        "max_attempts": 2,
    })
    firestore_service.register_device(household["elder_id"], "fcm-token-on-the-phone")

    result = reminders.run(EIGHT_AM_IST)

    assert len(result["reminders_sent"]) == 2
    assert all(r["reached_a_phone"] for r in result["reminders_sent"])
    assert [r["alerted"] for r in result["reminders_sent"]].count(True) == 1


# ---------------- what the dashboard is told ----------------


def test_the_dashboard_can_tell_the_two_apart(client, db, firestore_service, household):
    """Anchored to now, because /today is read in the elder's real day."""
    from zoneinfo import ZoneInfo

    from app.services.reminder_service import ReminderService

    due = datetime.now(ZoneInfo("Asia/Kolkata")) - timedelta(minutes=1)
    firestore_service.update_medication(
        household["medication_id"],
        {"schedule_times": [due.strftime("%H:%M")], "schedule_time": due.strftime("%H:%M")},
    )

    ReminderService(db).run(due.astimezone(timezone.utc))

    today = client.get(
        f"/api/elders/{household['elder_id']}/today",
        headers={"X-Caregiver-Id": "caregiver_1"},
    ).json()

    reminded = [i for i in today["items"] if i["status"] != "UPCOMING"]
    assert reminded
    assert all(i["reached_a_phone"] is False for i in reminded)
