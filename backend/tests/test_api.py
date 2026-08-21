CAREGIVER = {"X-Caregiver-Id": "caregiver_1"}
INTRUDER = {"X-Caregiver-Id": "caregiver_2"}


def test_health_reports_the_configured_model(client):
    body = client.get("/health").json()

    assert body["status"] == "healthy"
    assert body["model"].startswith("gemini")


def test_caregiver_setup_flow(client):
    elder = client.post(
        "/api/elders",
        json={"name": "Amma", "timezone": "Asia/Kolkata", "preferred_language": "te"},
        headers=CAREGIVER,
    )
    assert elder.status_code == 201
    elder_id = elder.json()["id"]

    medication = client.post(
        "/api/medications",
        json={
            "elder_id": elder_id,
            "name": "Amlodipine",
            "dose": "1 tablet",
            "food_instruction": "BEFORE_FOOD",
            "schedule_times": ["08:00"],
        },
        headers=CAREGIVER,
    )
    assert medication.status_code == 201
    assert medication.json()["schedule_time"] == "08:00"

    listed = client.get("/api/elders", headers=CAREGIVER).json()
    assert [e["id"] for e in listed] == [elder_id]


def test_another_caregiver_cannot_reach_an_elder(client):
    elder_id = client.post(
        "/api/elders", json={"name": "Amma"}, headers=CAREGIVER
    ).json()["id"]

    assert client.get(f"/api/elders/{elder_id}", headers=INTRUDER).status_code == 403
    assert client.get("/api/elders", headers=INTRUDER).json() == []

    denied = client.post(
        "/api/medications",
        json={
            "elder_id": elder_id,
            "name": "Something else",
            "dose": "2 tablets",
            "food_instruction": "AFTER_FOOD",
            "schedule_times": ["09:00"],
        },
        headers=INTRUDER,
    )
    assert denied.status_code == 403


def test_schedule_times_must_be_real_clock_times(client):
    elder_id = client.post(
        "/api/elders", json={"name": "Amma"}, headers=CAREGIVER
    ).json()["id"]

    for bad in ("25:00", "8:00", "08:70", "morning"):
        response = client.post(
            "/api/medications",
            json={
                "elder_id": elder_id,
                "name": "Amlodipine",
                "dose": "1 tablet",
                "food_instruction": "BEFORE_FOOD",
                "schedule_times": [bad],
            },
            headers=CAREGIVER,
        )
        assert response.status_code == 422, bad


def test_the_worker_endpoint_rejects_callers_without_the_token(client):
    assert client.post("/api/internal/reminders/process").status_code == 403

    ok = client.post(
        "/api/internal/reminders/process",
        headers={"X-Worker-Token": "local-worker-token"},
    )
    assert ok.status_code == 200


def test_an_elder_cannot_act_on_another_elders_reminder(client, db):
    from app.services.medication_event_service import MedicationEventService

    elder_id = client.post(
        "/api/elders", json={"name": "Amma"}, headers=CAREGIVER
    ).json()["id"]
    medication_id = client.post(
        "/api/medications",
        json={
            "elder_id": elder_id,
            "name": "Amlodipine",
            "dose": "1 tablet",
            "food_instruction": "BEFORE_FOOD",
            "schedule_times": ["08:00"],
        },
        headers=CAREGIVER,
    ).json()["id"]

    from datetime import datetime, timezone

    events = MedicationEventService(db)
    event_id = events.create_event(
        medication_id=medication_id,
        elder_id=elder_id,
        scheduled_at=datetime.now(timezone.utc),
        retry_after_minutes=10,
        max_attempts=2,
    )
    events.record_reminder_sent(event_id)

    stranger = client.post(
        f"/api/reminders/{event_id}/taken", headers={"X-Elder-Id": "elder_999"}
    )
    assert stranger.status_code == 404

    assert client.post(f"/api/reminders/{event_id}/taken").status_code == 401

    owner = client.post(
        f"/api/reminders/{event_id}/taken", headers={"X-Elder-Id": elder_id}
    )
    assert owner.status_code == 200
    assert owner.json()["status"] == "TAKEN"


def test_acting_on_a_finished_reminder_is_a_conflict_not_a_crash(client, db):
    from datetime import datetime, timezone

    from app.services.medication_event_service import MedicationEventService

    elder_id = client.post(
        "/api/elders", json={"name": "Amma"}, headers=CAREGIVER
    ).json()["id"]
    medication_id = client.post(
        "/api/medications",
        json={
            "elder_id": elder_id,
            "name": "Amlodipine",
            "dose": "1 tablet",
            "food_instruction": "BEFORE_FOOD",
            "schedule_times": ["08:00"],
        },
        headers=CAREGIVER,
    ).json()["id"]

    events = MedicationEventService(db)
    event_id = events.create_event(
        medication_id=medication_id,
        elder_id=elder_id,
        scheduled_at=datetime.now(timezone.utc),
        retry_after_minutes=10,
        max_attempts=2,
    )
    events.record_reminder_sent(event_id)
    events.decline_event(event_id, "not today")

    conflict = client.post(
        f"/api/reminders/{event_id}/snooze",
        json={"minutes": 10},
        headers={"X-Elder-Id": elder_id},
    )
    assert conflict.status_code == 409


def test_snooze_beyond_an_hour_is_rejected(client, db):
    elder_id = client.post(
        "/api/elders", json={"name": "Amma"}, headers=CAREGIVER
    ).json()["id"]

    response = client.post(
        "/api/reminders/anything/snooze",
        json={"minutes": 600},
        headers={"X-Elder-Id": elder_id},
    )
    assert response.status_code == 422


def test_worker_token_tolerates_trailing_whitespace(client):
    """A secret written from a shell usually carries a trailing newline.

    Cloud Run keeps it in the env var while command substitution strips it on
    the sending side, so the two must still compare equal.
    """
    assert (
        client.post(
            "/api/internal/reminders/process",
            headers={"X-Worker-Token": "local-worker-token\n"},
        ).status_code
        == 200
    )

    assert (
        client.post(
            "/api/internal/reminders/process",
            headers={"X-Worker-Token": "not-the-token"},
        ).status_code
        == 403
    )


def test_updating_an_elders_timezone(client):
    elder_id = client.post(
        "/api/elders",
        json={"name": "Amma", "timezone": "Asia/Kolkata"},
        headers=CAREGIVER,
    ).json()["id"]

    response = client.patch(
        f"/api/elders/{elder_id}",
        json={"timezone": "America/New_York"},
        headers=CAREGIVER,
    )

    assert response.status_code == 200
    assert response.json()["timezone"] == "America/New_York"


def test_a_timezone_the_server_cannot_resolve_is_rejected(client):
    """Silently falling back to UTC would schedule every dose at the wrong hour."""
    elder_id = client.post(
        "/api/elders", json={"name": "Amma"}, headers=CAREGIVER
    ).json()["id"]

    response = client.patch(
        f"/api/elders/{elder_id}",
        json={"timezone": "Mars/Olympus_Mons"},
        headers=CAREGIVER,
    )

    assert response.status_code == 422


def test_creating_an_elder_with_an_unknown_timezone_is_rejected(client):
    response = client.post(
        "/api/elders",
        json={"name": "Amma", "timezone": "Not/AZone"},
        headers=CAREGIVER,
    )

    assert response.status_code == 422


def test_another_caregiver_cannot_change_an_elders_timezone(client):
    elder_id = client.post(
        "/api/elders", json={"name": "Amma"}, headers=CAREGIVER
    ).json()["id"]

    response = client.patch(
        f"/api/elders/{elder_id}",
        json={"timezone": "America/New_York"},
        headers=INTRUDER,
    )

    assert response.status_code == 403


def test_a_patch_with_nothing_in_it_is_a_bad_request(client):
    elder_id = client.post(
        "/api/elders", json={"name": "Amma"}, headers=CAREGIVER
    ).json()["id"]

    response = client.patch(f"/api/elders/{elder_id}", json={}, headers=CAREGIVER)

    assert response.status_code == 400


def _elder_with_medication(client, time: str = "08:00") -> tuple[str, str]:
    elder_id = client.post(
        "/api/elders",
        json={"name": "Amma", "timezone": "Asia/Kolkata"},
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


def test_removing_a_medication_clears_it_from_today(client, db):
    """The row vanishing is the whole point: it is how remove looks."""
    from datetime import datetime, timezone as tz

    from app.services.medication_event_service import MedicationEventService

    elder_id, medication_id = _elder_with_medication(client)

    events = MedicationEventService(db)
    events.create_event(
        medication_id=medication_id,
        elder_id=elder_id,
        scheduled_at=datetime.now(tz.utc),
        retry_after_minutes=10,
        max_attempts=2,
    )

    before = client.get(f"/api/elders/{elder_id}/today", headers=CAREGIVER).json()
    assert any(i["medication_id"] == medication_id for i in before["items"])

    assert client.delete(
        f"/api/medications/{medication_id}", headers=CAREGIVER
    ).status_code == 204

    after = client.get(f"/api/elders/{elder_id}/today", headers=CAREGIVER).json()
    assert [i for i in after["items"] if i["medication_id"] == medication_id] == []


def test_the_elder_sees_every_dose_due_at_once(client, db):
    """Two tablets at eight is normal; returning one hid the other until it
    escalated behind the elder's back."""
    from datetime import datetime, timezone as tz

    from app.services.medication_event_service import MedicationEventService

    elder_id, first = _elder_with_medication(client, "08:00")
    second = client.post(
        "/api/medications",
        json={
            "elder_id": elder_id,
            "name": "Metformin",
            "dose": "1 tablet",
            "food_instruction": "AFTER_FOOD",
            "schedule_times": ["08:00"],
        },
        headers=CAREGIVER,
    ).json()["id"]

    events = MedicationEventService(db)
    now = datetime.now(tz.utc)
    for index, medication_id in enumerate((first, second)):
        event_id = events.create_event(
            medication_id=medication_id,
            elder_id=elder_id,
            scheduled_at=now,
            retry_after_minutes=10,
            max_attempts=2,
        )
        events.record_reminder_sent(event_id, now)

    body = client.get(
        "/api/reminders/active", headers={"X-Elder-Id": elder_id}
    ).json()

    assert body["remaining"] == 2
    assert {r["medication_name"] for r in body["reminders"]} == {
        "Eye Drops",
        "Metformin",
    }
    # Older clients read this field and must still see a usable reminder.
    assert body["reminder"] == body["reminders"][0]


def test_a_removed_medication_disappears_from_the_elders_queue(client, db):
    from datetime import datetime, timezone as tz

    from app.services.medication_event_service import MedicationEventService

    elder_id, medication_id = _elder_with_medication(client)

    events = MedicationEventService(db)
    now = datetime.now(tz.utc)
    event_id = events.create_event(
        medication_id=medication_id,
        elder_id=elder_id,
        scheduled_at=now,
        retry_after_minutes=10,
        max_attempts=2,
    )
    events.record_reminder_sent(event_id, now)

    client.delete(f"/api/medications/{medication_id}", headers=CAREGIVER)

    body = client.get(
        "/api/reminders/active", headers={"X-Elder-Id": elder_id}
    ).json()

    assert body["active"] is False
    assert body["reminders"] == []
