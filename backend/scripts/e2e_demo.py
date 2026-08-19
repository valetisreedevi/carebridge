"""End-to-end run against real Firestore, real Cloud Storage and real Gemini.

Walks the two demo storylines from the handoff: a conversation that ends in a
confirmation, and a silence that ends in an escalation.

    python scripts/e2e_demo.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.medication_event_service import (  # noqa: E402
    MedicationEventService,
    event_document_id,
)
from app.services.reminder_service import ReminderService  # noqa: E402

CAREGIVER = {"X-Caregiver-Id": "e2e-caregiver"}
client = TestClient(app)

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {label}")
    else:
        failed += 1
        print(f"  FAIL  {label}  {detail}")


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def main() -> int:
    section("1. Caregiver sets up an elder and a medication")

    elder = client.post(
        "/api/elders",
        json={"name": "Amma", "preferred_language": "te", "timezone": "Asia/Kolkata"},
        headers=CAREGIVER,
    )
    check("elder created", elder.status_code == 201, elder.text)
    elder_id = elder.json()["id"]

    medication = client.post(
        "/api/medications",
        json={
            "elder_id": elder_id,
            "name": "Amlodipine",
            "dose": "1 tablet",
            "food_instruction": "BEFORE_FOOD",
            "schedule_times": ["08:00"],
            "retry_after_minutes": 10,
            "max_attempts": 2,
        },
        headers=CAREGIVER,
    )
    check("medication created", medication.status_code == 201, medication.text)
    medication_id = medication.json()["id"]

    photo = client.post(
        f"/api/medications/{medication_id}/image-upload",
        files={"file": ("pill.png", _png(), "image/png")},
        headers=CAREGIVER,
    )
    check("medicine photo uploaded to GCS", photo.status_code == 200, photo.text)

    audio = client.post(
        f"/api/medications/{medication_id}/audio-upload",
        files={"file": ("voice.mp3", b"ID3fake-caregiver-audio", "audio/mpeg")},
        headers=CAREGIVER,
    )
    check("caregiver voice uploaded to GCS", audio.status_code == 200, audio.text)

    section("2. Reminder fires and reaches the elder")

    triggered = client.post(
        "/api/demo/trigger-reminder",
        json={"medication_id": medication_id},
        headers=CAREGIVER,
    )
    check("reminder dispatched", triggered.status_code == 200, triggered.text)
    event_id = triggered.json()["event_id"]

    elder_headers = {"X-Elder-Id": elder_id}
    active = client.get("/api/reminders/active", headers=elder_headers).json()
    check("elder device sees an active reminder", active["active"] is True)
    check(
        "reminder carries the configured medication",
        active["reminder"]["medication_name"] == "Amlodipine"
        and active["reminder"]["dose"] == "1 tablet",
    )
    check("photo is available to the elder", active["reminder"]["has_photo"])
    check(
        "caregiver voice is available to the elder",
        active["reminder"]["has_caregiver_audio"],
    )

    section("3. The elder talks to the agent (live Gemini)")

    def say(text: str) -> dict:
        response = client.post(
            "/api/agent/chat",
            json={"elder_id": elder_id, "event_id": event_id, "message": text},
            headers=elder_headers,
        )
        if response.status_code != 200:
            print(f"  !! agent error {response.status_code}: {response.text}")
            return {"reply": "", "tool_calls": [], "event_status": None}
        body = response.json()
        print(f'    elder: "{text}"')
        print(f'    agent: "{body["reply"]}"')
        print(f"    tools: {body['tool_calls']}  status: {body['event_status']}")
        return body

    question = say("Which medicine is it?")
    check(
        "agent answers from the record, not from memory",
        "amlodipine" in question["reply"].lower(),
        question["reply"],
    )
    check(
        "agent looked the reminder up",
        any("reminder" in t or "instruction" in t for t in question["tool_calls"]),
        str(question["tool_calls"]),
    )

    ambiguous = say("Okay.")
    check(
        "an ambiguous reply is NOT treated as confirmation",
        ambiguous["event_status"] != "TAKEN",
        f"status became {ambiguous['event_status']}",
    )

    dose_change = say("Make it two tablets from now on.")
    check(
        "agent refuses to change the dose",
        dose_change["event_status"] != "TAKEN"
        and "confirm_medication_taken" not in dose_change["tool_calls"],
        str(dose_change["tool_calls"]),
    )

    snooze = say("Remind me in ten minutes.")
    check(
        "snooze recorded",
        snooze["event_status"] == "SNOOZED",
        f"status {snooze['event_status']}",
    )

    taken = say("I have taken it now.")
    check(
        "confirmation recorded",
        taken["event_status"] == "TAKEN",
        f"status {taken['event_status']}",
    )

    section("4. Caregiver dashboard reflects it")

    today = client.get(f"/api/elders/{elder_id}/today", headers=CAREGIVER).json()
    confirmed = [i for i in today["items"] if i["status"] == "TAKEN"]
    check("dashboard shows the medication as taken", len(confirmed) == 1, str(today))

    section("5. Silence escalates to the caregiver")

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0) + timedelta(
        minutes=1
    )
    events = MedicationEventService()
    silent_event_id = event_document_id(medication_id, now)
    events.create_event(
        event_id=silent_event_id,
        medication_id=medication_id,
        elder_id=elder_id,
        scheduled_at=now,
        retry_after_minutes=10,
        max_attempts=2,
    )

    worker = ReminderService()
    first = worker.process_due_events(now)
    second = worker.process_due_events(now + timedelta(minutes=10))
    third = worker.process_due_events(now + timedelta(minutes=20))

    mine = lambda batch: [  # noqa: E731
        r for r in batch if r["event_id"] == silent_event_id
    ]

    check("attempt 1 sent", len(mine(first["reminders_sent"])) == 1)
    check("attempt 2 sent", len(mine(second["reminders_sent"])) == 1)
    check("escalated after the limit", len(mine(third["escalations"])) == 1)

    if mine(third["escalations"]):
        message = mine(third["escalations"])[0]["message"]
        print(f'    alert: "{message}"')
        check("alert says not confirmed, never not taken", "has not confirmed" in message)

    alerts = client.get("/api/caregivers/me/alerts", headers=CAREGIVER).json()
    check("caregiver sees the alert", any(a["reason"] == "NOT_CONFIRMED" for a in alerts))

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


def _png() -> bytes:
    import base64

    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


if __name__ == "__main__":
    sys.exit(main())
