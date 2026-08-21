"""A caregiver's action must touch their own elder or nothing.

"Remind now" used to finish by running a whole worker pass. That acted on every
household whose dose was due at that moment and returned their elders' names
and medicines to whoever pressed the button.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.medication_event_service import (
    MedicationEventService,
    event_document_id,
)
from app.services.reminder_service import ReminderService


def _household(firestore_service, caregiver_id, elder_name):
    """A caregiver, their elder, and one medicine due a minute ago."""
    firestore_service.upsert_caregiver(caregiver_id, name=caregiver_id)
    elder_id = firestore_service.create_elder(
        name=elder_name, caregiver_id=caregiver_id, elder_timezone="UTC"
    )

    due = datetime.now(timezone.utc) - timedelta(minutes=1)
    medication_id = firestore_service.create_medication({
        "elder_id": elder_id,
        "name": f"{elder_name}'s tablet",
        "dose": "1 tablet",
        "food_instruction": "AFTER_FOOD",
        "schedule_times": [due.strftime("%H:%M")],
        "schedule_time": due.strftime("%H:%M"),
        "retry_after_minutes": 10,
        "max_attempts": 2,
    })

    return {"elder_id": elder_id, "medication_id": medication_id, "due": due}


@pytest.fixture
def two_households(firestore_service, db):
    """Two unrelated families, the second one with a dose already due.

    The second household is left in exactly the state the system is in whenever
    a scheduler tick has not landed yet: a live event, waiting to be acted on.
    """
    mine = _household(firestore_service, "caregiver_mine", "Amma")
    theirs = _household(firestore_service, "caregiver_theirs", "Beatrice")

    MedicationEventService(db).create_event(
        medication_id=theirs["medication_id"],
        elder_id=theirs["elder_id"],
        scheduled_at=theirs["due"],
        retry_after_minutes=10,
        max_attempts=2,
        event_id=event_document_id(theirs["medication_id"], theirs["due"]),
    )

    return {"mine": mine, "theirs": theirs}


def test_response_names_only_the_caller_s_elder(client, two_households):
    response = client.post(
        f"/api/medications/{two_households['mine']['medication_id']}/remind-now",
        headers={"X-Caregiver-Id": "caregiver_mine"},
    )

    assert response.status_code == 200
    assert "Beatrice" not in response.text
    assert response.json()["elder"] == "Amma"


def test_another_household_is_not_reminded(client, db, two_households):
    client.post(
        f"/api/medications/{two_households['mine']['medication_id']}/remind-now",
        headers={"X-Caregiver-Id": "caregiver_mine"},
    )

    theirs = two_households["theirs"]
    untouched = MedicationEventService(db).get_event(
        event_document_id(theirs["medication_id"], theirs["due"])
    )

    assert untouched["status"] == "PENDING"
    assert untouched["attempt"] == 0


def test_the_caller_s_own_reminder_still_goes_out(client, db, two_households):
    response = client.post(
        f"/api/medications/{two_households['mine']['medication_id']}/remind-now",
        headers={"X-Caregiver-Id": "caregiver_mine"},
    )

    body = response.json()
    assert body["attempt"] == 1
    assert body["alerted"] is True

    event = MedicationEventService(db).get_event(body["event_id"])
    assert event["status"] == "REMINDER_SENT"


def test_the_scheduled_worker_still_reaches_every_household(db, two_households):
    """The narrowing is to the caregiver's action, not to the worker."""
    result = ReminderService(db).run(datetime.now(timezone.utc))

    reminded = {r["elder"] for r in result["reminders_sent"]}
    assert reminded == {"Amma", "Beatrice"}


def test_a_dose_already_taken_cannot_be_re_rung(client, db, two_households):
    mine = two_households["mine"]

    first = client.post(
        f"/api/medications/{mine['medication_id']}/remind-now",
        headers={"X-Caregiver-Id": "caregiver_mine"},
    ).json()

    MedicationEventService(db).confirm_event(first["event_id"])

    again = client.post(
        f"/api/medications/{mine['medication_id']}/remind-now",
        headers={"X-Caregiver-Id": "caregiver_mine"},
    )

    assert again.status_code == 409
