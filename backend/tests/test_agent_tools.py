from datetime import datetime, timezone

import pytest

from app.tools import medication_tools as tools


@pytest.fixture
def wired(db, monkeypatch, seeded, events):
    """Point every tool at the in-memory database."""
    from app.services import notification_service as notif_module

    monkeypatch.setattr(notif_module, "FCM_AVAILABLE", False)
    monkeypatch.setattr(tools, "FirestoreService", lambda *a, **k: _firestore(db))
    monkeypatch.setattr(tools, "MedicationEventService", lambda *a, **k: _events(db))
    monkeypatch.setattr(
        tools, "NotificationService", lambda *a, **k: notif_module.NotificationService(db)
    )

    event_id = events.create_event(
        medication_id=seeded["medication_id"],
        elder_id=seeded["elder_id"],
        scheduled_at=datetime.now(timezone.utc),
        retry_after_minutes=10,
        max_attempts=2,
    )
    events.record_reminder_sent(event_id)

    tools.set_context(
        tools.AgentContext(elder_id=seeded["elder_id"], event_id=event_id)
    )
    return {**seeded, "event_id": event_id}


def _firestore(db):
    from app.services.firestore_service import FirestoreService

    return FirestoreService(db)


def _events(db):
    from app.services.medication_event_service import MedicationEventService

    return MedicationEventService(db)


def test_the_reminder_the_agent_sees_is_the_configured_one(wired):
    result = tools.get_current_reminder()

    assert result["success"]
    assert result["medication_name"] == "Amlodipine"
    assert result["dose"] == "1 tablet"
    assert result["food_instruction"] == "before food"


def test_confirming_records_taken(wired, events):
    result = tools.confirm_medication_taken()

    assert result["status"] == "TAKEN"
    assert events.get_event(wired["event_id"])["status"] == "TAKEN"


def test_confirming_twice_is_reported_not_repeated(wired):
    tools.confirm_medication_taken()
    again = tools.confirm_medication_taken()

    assert again["success"]
    assert "already" in again["message"].lower()


def test_snooze_is_capped_so_a_reminder_cannot_be_pushed_off_the_day(wired, events):
    rejected = tools.snooze_reminder(600)

    assert not rejected["success"]
    assert events.get_event(wired["event_id"])["status"] == "REMINDER_SENT"

    accepted = tools.snooze_reminder(10)
    assert accepted["status"] == "SNOOZED"


def test_declining_alerts_the_caregiver(wired, notifications, seeded):
    result = tools.record_decline("feeling unwell")

    assert result["status"] == "DECLINED"

    alerts = notifications.list_for_caregiver(seeded["caregiver_id"])
    assert [a["reason"] for a in alerts] == ["DECLINED"]


def test_tools_refuse_to_act_when_the_session_has_no_reminder(db, monkeypatch, seeded):
    monkeypatch.setattr(tools, "MedicationEventService", lambda *a, **k: _events(db))
    tools.set_context(tools.AgentContext(elder_id=seeded["elder_id"], event_id=None))

    for call in (
        tools.get_current_reminder,
        tools.get_medication_instructions,
        tools.confirm_medication_taken,
        lambda: tools.snooze_reminder(10),
        lambda: tools.record_decline("no"),
    ):
        result = call()
        assert result["success"] is False


def test_an_event_belonging_to_another_elder_is_invisible(wired, db, monkeypatch):
    """The model cannot reach another family's record by supplying an id."""
    tools.set_context(
        tools.AgentContext(elder_id="someone_else", event_id=wired["event_id"])
    )

    result = tools.get_current_reminder()

    assert result["success"] is False
    assert _events(db).get_event(wired["event_id"])["status"] == "REMINDER_SENT"


def test_a_finished_reminder_cannot_be_reopened_through_a_tool(wired):
    tools.record_decline("not today")

    result = tools.confirm_medication_taken()

    assert result["success"] is False
    assert "DECLINED" in result["message"]
