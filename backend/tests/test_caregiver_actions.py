"""What a caregiver can do about a dose without the elder's device.

The gap this closes: you phone, you hear "yes, I took it", and until now there
was nothing you could do with that. The row stayed red for ever and the record
stayed permanently wrong.
"""

from datetime import datetime, timezone as tz

CAREGIVER = {"X-Caregiver-Id": "caregiver_1"}
INTRUDER = {"X-Caregiver-Id": "caregiver_2"}


def _setup(client, time: str = "08:00") -> tuple[str, str]:
    elder_id = client.post(
        "/api/elders",
        json={"name": "Nanna", "timezone": "Asia/Kolkata"},
        headers=CAREGIVER,
    ).json()["id"]

    medication_id = client.post(
        "/api/medications",
        json={
            "elder_id": elder_id,
            "name": "Eye Drops",
            "dose": "1 drop",
            "food_instruction": "AFTER_FOOD",
            "schedule_times": [time],
        },
        headers=CAREGIVER,
    ).json()["id"]

    return elder_id, medication_id


def _today(client, elder_id: str) -> list[dict]:
    return client.get(f"/api/elders/{elder_id}/today", headers=CAREGIVER).json()["items"]


def test_a_dose_that_never_fired_can_still_be_recorded(client):
    """The commonest case: nothing was sent, but she took it anyway."""
    elder_id, medication_id = _setup(client)

    response = client.post(
        f"/api/medications/{medication_id}/mark-taken",
        json={"local_time": "08:00"},
        headers=CAREGIVER,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "TAKEN"

    row = [i for i in _today(client, elder_id) if i["local_time"] == "08:00"][0]
    assert row["status"] == "TAKEN"


def test_the_record_says_who_said_so(client):
    """If this ever reaches a clinician, the family's word is not the elder's."""
    _, medication_id = _setup(client)

    body = client.post(
        f"/api/medications/{medication_id}/mark-taken",
        json={"local_time": "08:00"},
        headers=CAREGIVER,
    ).json()

    assert body["confirmed_source"] == "CAREGIVER"


def test_an_escalated_dose_can_be_closed_by_the_caregiver(client, db):
    from app.services.medication_event_service import MedicationEventService

    elder_id, medication_id = _setup(client)
    events = MedicationEventService(db)

    event_id = events.create_event(
        medication_id=medication_id,
        elder_id=elder_id,
        scheduled_at=datetime.now(tz.utc),
        retry_after_minutes=10,
        max_attempts=2,
    )
    events.record_reminder_sent(event_id)
    events.escalate_event(event_id)

    local_time = _today(client, elder_id)[0]["local_time"]
    response = client.post(
        f"/api/medications/{medication_id}/mark-taken",
        json={"local_time": local_time},
        headers=CAREGIVER,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "TAKEN"


def test_someone_elses_elder_cannot_be_touched(client):
    _, medication_id = _setup(client)

    assert client.post(
        f"/api/medications/{medication_id}/mark-taken",
        json={"local_time": "08:00"},
        headers=INTRUDER,
    ).status_code == 403


def test_a_nonsense_time_is_rejected(client):
    _, medication_id = _setup(client)

    assert client.post(
        f"/api/medications/{medication_id}/mark-taken",
        json={"local_time": "half past eight"},
        headers=CAREGIVER,
    ).status_code == 422


def test_remind_now_has_a_real_name(client):
    """It used to be /api/demo/trigger-reminder, live in production."""
    _, medication_id = _setup(client)

    assert client.post(
        f"/api/medications/{medication_id}/remind-now", headers=CAREGIVER
    ).status_code == 200

    assert client.post(
        "/api/demo/trigger-reminder",
        json={"medication_id": medication_id},
        headers=CAREGIVER,
    ).status_code == 404


def test_history_covers_the_requested_days(client):
    elder_id, _ = _setup(client)

    body = client.get(
        f"/api/elders/{elder_id}/history?days=7", headers=CAREGIVER
    ).json()

    assert len(body["days"]) == 7
    assert body["elder"]["name"] == "Nanna"
    assert all(set(day) >= {"date", "taken", "missed", "total"} for day in body["days"])


def test_history_counts_a_dose_the_caregiver_recorded(client):
    elder_id, medication_id = _setup(client)

    client.post(
        f"/api/medications/{medication_id}/mark-taken",
        json={"local_time": "08:00"},
        headers=CAREGIVER,
    )

    body = client.get(f"/api/elders/{elder_id}/history", headers=CAREGIVER).json()

    assert sum(day["taken"] for day in body["days"]) == 1


def test_history_is_capped_so_a_client_cannot_ask_for_a_decade(client):
    elder_id, _ = _setup(client)

    body = client.get(
        f"/api/elders/{elder_id}/history?days=9999", headers=CAREGIVER
    ).json()

    assert len(body["days"]) == 31
