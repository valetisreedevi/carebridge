"""Remind now has to ring a dose that exists.

It used to raise an event stamped with the current minute. That minute is not
a time anybody was prescribed, so every press invented a dose: an extra row in
today's list, an extra unit in "N of M taken", and an extra entry in the
week's adherence. In this project's live data every single event ever created
came from that button - not one real scheduled dose had ever fired.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

KOLKATA = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def household(firestore_service):
    """Two doses a day, in the elder's own timezone, with a phone paired."""
    firestore_service.upsert_caregiver("caregiver_1")
    elder_id = firestore_service.create_elder(
        name="Amma", caregiver_id="caregiver_1", elder_timezone="Asia/Kolkata"
    )
    medication_id = firestore_service.create_medication({
        "elder_id": elder_id,
        "name": "Fever Tablet",
        "dose": "1 tablet",
        "food_instruction": "AFTER_FOOD",
        "schedule_times": ["08:00", "20:00"],
        "schedule_time": "08:00",
        "retry_after_minutes": 10,
        "max_attempts": 2,
    })
    firestore_service.register_device(elder_id, "fcm-token-on-the-phone")

    return {"elder_id": elder_id, "medication_id": medication_id}


def _remind(client, medication_id, local_time=None):
    body = {"local_time": local_time} if local_time else None
    return client.post(
        f"/api/medications/{medication_id}/remind-now",
        json=body,
        headers={"X-Caregiver-Id": "caregiver_1"},
    )


def _scheduled_local_times(db, elder_id):
    from app.services.medication_event_service import MedicationEventService

    return sorted(
        e["scheduled_at"].astimezone(KOLKATA).strftime("%H:%M")
        for e in MedicationEventService(db)._for_elder(elder_id)
    )


# ---------------- it rings a real dose ----------------


def test_the_named_dose_is_the_one_rung(client, db, household):
    response = _remind(client, household["medication_id"], "20:00")

    assert response.status_code == 200
    assert _scheduled_local_times(db, household["elder_id"]) == ["20:00"]


def test_the_other_scheduled_dose_is_left_alone(client, db, household):
    _remind(client, household["medication_id"], "08:00")

    assert _scheduled_local_times(db, household["elder_id"]) == ["08:00"]


def test_pressing_it_repeatedly_does_not_multiply_the_day(client, db, household):
    """Three presses used to mean three tablets that never existed."""
    for _ in range(3):
        _remind(client, household["medication_id"], "08:00")

    assert _scheduled_local_times(db, household["elder_id"]) == ["08:00"]


def test_without_a_named_dose_it_picks_a_scheduled_one(client, db, household):
    _remind(client, household["medication_id"])

    times = _scheduled_local_times(db, household["elder_id"])
    assert len(times) == 1
    assert times[0] in {"08:00", "20:00"}


def test_it_never_invents_the_current_minute(client, db, household):
    _remind(client, household["medication_id"])

    now_local = datetime.now(KOLKATA).strftime("%H:%M")
    times = _scheduled_local_times(db, household["elder_id"])

    if now_local not in {"08:00", "20:00"}:
        assert now_local not in times


def test_the_attempt_is_recorded_against_that_dose(client, db, household):
    body = _remind(client, household["medication_id"], "08:00").json()

    assert body["attempt"] == 1
    assert body["reached_a_phone"] is True


# ---------------- it refuses rather than inventing ----------------


def test_a_time_that_is_not_scheduled_is_refused(client, household):
    response = _remind(client, household["medication_id"], "13:37")

    assert response.status_code == 409
    assert "no dose scheduled today" in response.json()["detail"]


def test_a_refusal_writes_nothing(client, db, household):
    _remind(client, household["medication_id"], "13:37")

    assert _scheduled_local_times(db, household["elder_id"]) == []


def test_a_medicine_with_no_times_is_refused(client, db, firestore_service, household):
    empty = firestore_service.create_medication({
        "elder_id": household["elder_id"],
        "name": "Eye Drops",
        "dose": "1 drop",
        "food_instruction": "ANY_TIME",
        "schedule_times": [],
    })

    response = _remind(client, empty)

    assert response.status_code == 409
    assert "Eye Drops" in response.json()["detail"]


def test_a_dose_already_taken_is_not_rung_again(client, db, household):
    first = _remind(client, household["medication_id"], "08:00").json()

    from app.services.medication_event_service import MedicationEventService

    MedicationEventService(db).confirm_event(first["event_id"])

    assert _remind(client, household["medication_id"], "08:00").status_code == 409


# ---------------- today's view stays honest ----------------


def test_the_day_does_not_grow_a_row(client, db, household):
    before = client.get(
        f"/api/elders/{household['elder_id']}/today",
        headers={"X-Caregiver-Id": "caregiver_1"},
    ).json()

    _remind(client, household["medication_id"], "08:00")

    after = client.get(
        f"/api/elders/{household['elder_id']}/today",
        headers={"X-Caregiver-Id": "caregiver_1"},
    ).json()

    assert len(after["items"]) == len(before["items"])
    assert sorted(i["local_time"] for i in after["items"]) == ["08:00", "20:00"]
