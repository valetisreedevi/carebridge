import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.fake_firestore import FakeFirestore  # noqa: E402


@pytest.fixture(autouse=True)
def no_model_calls(monkeypatch):
    """The analyst never runs in tests.

    It is an optional layer over figures that are already final, so leaving it
    live would make the suite slow, networked and non-deterministic in exchange
    for testing nothing. The two things worth asserting — that its wording is
    used when it arrives, and that its absence changes nothing — have their own
    tests, which opt back in explicitly.
    """
    from app.services import narration_service

    async def no_narration(*args, **kwargs):
        return None

    monkeypatch.setattr(
        narration_service.NarrationService, "narrate", no_narration
    )
    monkeypatch.setattr(
        narration_service.NarrationService,
        "narrate_blocking",
        lambda *args, **kwargs: None,
    )


@pytest.fixture
def db() -> FakeFirestore:
    return FakeFirestore()


@pytest.fixture
def firestore_service(db):
    from app.services.firestore_service import FirestoreService

    return FirestoreService(db)


@pytest.fixture
def events(db):
    from app.services.medication_event_service import MedicationEventService

    return MedicationEventService(db)


@pytest.fixture
def notifications(db, monkeypatch):
    from app.services import notification_service as module

    # No FCM in tests; dispatches are recorded to the notifications collection.
    monkeypatch.setattr(module, "FCM_AVAILABLE", False)
    return module.NotificationService(db)


@pytest.fixture
def reminders(db, monkeypatch):
    from app.services import notification_service as notif_module
    from app.services.reminder_service import ReminderService

    monkeypatch.setattr(notif_module, "FCM_AVAILABLE", False)
    return ReminderService(db)


@pytest.fixture
def seeded(firestore_service, db):
    """A household that is properly set up: caregiver, elder, medicine, phone.

    The phone matters. Without a registered device nothing can be delivered,
    and the worker now says so rather than reporting the dose as unanswered —
    which is a different scenario, and has its own tests.
    """
    firestore_service.upsert_caregiver("caregiver_1", name="Family Member")

    elder_id = firestore_service.create_elder(
        name="Amma",
        caregiver_id="caregiver_1",
        preferred_language="te",
        elder_timezone="Asia/Kolkata",
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

    firestore_service.register_device(elder_id, "fcm-token-on-ammas-phone")

    return {
        "caregiver_id": "caregiver_1",
        "elder_id": elder_id,
        "medication_id": medication_id,
    }


@pytest.fixture
def client(db, monkeypatch):
    """The whole app, wired to the in-memory Firestore."""
    from app.api import deps
    from app.services import notification_service as notif_module
    from app.services.conversation_service import ConversationService
    from app.services.firestore_service import FirestoreService
    from app.services.medication_event_service import MedicationEventService
    from app.services.reminder_service import ReminderService

    monkeypatch.setattr(notif_module, "FCM_AVAILABLE", False)

    for name, factory in (
        ("firestore_service", lambda: FirestoreService(db)),
        ("event_service", lambda: MedicationEventService(db)),
        ("notification_service", lambda: notif_module.NotificationService(db)),
        ("reminder_service", lambda: ReminderService(db)),
        ("conversation_service", lambda: ConversationService(db)),
        ("storage_service", lambda: None),
    ):
        monkeypatch.setattr(deps, name, factory)

    from app.main import app

    return TestClient(app)
