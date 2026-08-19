"""Proves the autonomous loop runs in the cloud.

Sets up a medication with a one-minute retry, fires it once, then stops
touching it. Cloud Scheduler drives every step from there: the second reminder
and the escalation must appear on their own.

    python scripts/verify_escalation.py https://carebridge-api-....run.app
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_deployed import Client, identity_token  # noqa: E402

CAREGIVER = {"X-Caregiver-Id": "escalation-check"}
POLL_SECONDS = 20
GIVE_UP_AFTER = 360


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    client = Client(sys.argv[1], identity_token())

    print(f"\nAgainst {client.base}")
    print("Setting up a medication that retries after one minute, twice.\n")

    _, elder = client.call(
        "POST",
        "/api/elders",
        {"name": "Amma", "timezone": "Asia/Kolkata", "preferred_language": "en"},
        CAREGIVER,
    )
    elder_id = elder["id"]

    _, medication = client.call(
        "POST",
        "/api/medications",
        {
            "elder_id": elder_id,
            "name": "Metformin",
            "dose": "1 tablet",
            "food_instruction": "AFTER_FOOD",
            "schedule_times": ["08:00"],
            "retry_after_minutes": 1,
            "max_attempts": 2,
        },
        CAREGIVER,
    )
    medication_id = medication["id"]

    status, triggered = client.call(
        "POST", "/api/demo/trigger-reminder", {"medication_id": medication_id}, CAREGIVER
    )
    if status != 200:
        print(f"  FAIL  could not fire the first reminder: {triggered}")
        return 1

    event_id = triggered["event_id"]
    print(f"  Fired attempt 1 for event {event_id}.")
    print("  Nothing else will touch it. Waiting on Cloud Scheduler.\n")

    seen = {"attempt_2": False, "escalated": False}
    started = time.time()

    while time.time() - started < GIVE_UP_AFTER:
        time.sleep(POLL_SECONDS)

        _, event = client.call(
            "GET", f"/api/medication-events/{event_id}", None, {"X-Elder-Id": elder_id}
        )
        attempt = event.get("attempt", 0)
        state = event.get("status")
        elapsed = int(time.time() - started)

        print(f"  [{elapsed:>3}s] status={state} attempt={attempt}")

        if attempt >= 2 and not seen["attempt_2"]:
            seen["attempt_2"] = True
            print("  PASS  the scheduler sent a second reminder on its own")

        if state == "ESCALATED":
            seen["escalated"] = True
            print("  PASS  the scheduler escalated on its own")
            break

    if not seen["escalated"]:
        print("\n  FAIL  no escalation within the time limit")
        return 1

    status, alerts = client.call("GET", "/api/caregivers/me/alerts", None, CAREGIVER)
    mine = [a for a in alerts if a.get("event_id") == event_id]

    if not mine:
        print("  FAIL  no caregiver alert was recorded")
        return 1

    message = mine[0]["message"]
    print(f'\n  Alert: "{message}"')

    if "has not confirmed" not in message or "not taken" in message.lower():
        print("  FAIL  alert wording is wrong")
        return 1

    print("  PASS  alert reached the caregiver with the right wording")
    print("\nThe autonomous loop works in the cloud.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
