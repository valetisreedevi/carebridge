"""The elder's own language reaches the screen and the model.

CareBridge has stored preferred_language since the first version and nothing
ever read it: the screen was hardcoded to English and the agent was never told
what to answer in. These tests hold that wiring in place, including the case
that made it a per-reminder field rather than a per-device one — a phone on a
side table shared by two people who do not read the same language.
"""

from datetime import datetime, timezone as tz

from app.services.medication_event_service import MedicationEventService

CAREGIVER = {"X-Caregiver-Id": "caregiver_1"}


def _elder(client, name: str, language: str | None) -> str:
    body: dict = {"name": name, "timezone": "Asia/Kolkata"}
    if language is not None:
        body["preferred_language"] = language

    return client.post("/api/elders", json=body, headers=CAREGIVER).json()["id"]


def _due_medication(client, db, elder_id: str, name: str) -> str:
    medication_id = client.post(
        "/api/medications",
        json={
            "elder_id": elder_id,
            "name": name,
            "dose": "1 tablet",
            "food_instruction": "AFTER_FOOD",
            "schedule_times": ["08:00"],
        },
        headers=CAREGIVER,
    ).json()["id"]

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
    return event_id


def _active(client, elder_id: str) -> dict:
    return client.get(
        "/api/reminders/active", headers={"X-Elder-Id": elder_id}
    ).json()


def test_the_reminder_carries_the_language_her_family_chose(client, db):
    elder_id = _elder(client, "Amma", "te")
    _due_medication(client, db, elder_id, "Amlodipine")

    assert _active(client, elder_id)["reminder"]["elder_language"] == "te"


def test_an_elder_with_no_language_recorded_gets_english(client, db):
    """Never null. The screen reads this straight into a lookup, and a household
    that predates the picker must still get a working screen."""
    elder_id = _elder(client, "Nanna", None)
    _due_medication(client, db, elder_id, "Metformin")

    assert _active(client, elder_id)["reminder"]["elder_language"] == "en"


def test_changing_the_language_afterwards_reaches_the_screen(client, db):
    """Amma already existed before the picker did, so the only way to reach her
    is the settings control, not the add-someone form."""
    elder_id = _elder(client, "Amma", "en")
    _due_medication(client, db, elder_id, "Amlodipine")

    client.patch(
        f"/api/elders/{elder_id}",
        json={"preferred_language": "te"},
        headers=CAREGIVER,
    )

    assert _active(client, elder_id)["reminder"]["elder_language"] == "te"


def test_a_shared_phone_carries_a_language_per_person(client, db):
    """The reason this is on the reminder and not on the device.

    One phone, two people, two languages. Each reminder has to bring its own or
    whoever is second reads the first one's.
    """
    amma = _elder(client, "Amma", "te")
    nanna = _elder(client, "Nanna", "en")
    _due_medication(client, db, amma, "Amlodipine")
    _due_medication(client, db, nanna, "Metformin")

    languages = {
        _active(client, amma)["reminder"]["elder_language"],
        _active(client, nanna)["reminder"]["elder_language"],
    }

    assert languages == {"te", "en"}


def test_the_agent_is_told_which_language_to_answer_in(client, db, monkeypatch):
    """The model cannot answer in Telugu if nothing tells it to.

    get_current_reminder is the one tool the prompt requires before the agent
    says anything, which makes it the right place to carry this.
    """
    from app.services import firestore_service as firestore_module
    from app.services import medication_event_service as event_module
    from app.tools import medication_tools

    monkeypatch.setattr(firestore_module, "get_db", lambda: db)
    monkeypatch.setattr(event_module, "get_db", lambda: db)

    elder_id = _elder(client, "Amma", "te")
    event_id = _due_medication(client, db, elder_id, "Amlodipine")

    medication_tools.set_context(
        medication_tools.AgentContext(elder_id=elder_id, event_id=event_id)
    )
    reminder = medication_tools.get_current_reminder()

    assert reminder["success"] is True
    assert reminder["speak_language"] == "te"
    # The medicine name is never translated, so it must arrive as typed.
    assert reminder["medication_name"] == "Amlodipine"
