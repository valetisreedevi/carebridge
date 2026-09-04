"""READ-ONLY. What the elder's device would be handed right now."""

from datetime import datetime, timezone

from google.cloud import firestore

db = firestore.Client(project="carecompanion-506011")
ELDER = "6nQXfpLKzOywKnM3jyHH"

# Mirrors OPEN_STATUSES in medication_event_service.
OPEN = {"REMINDER_SENT", "SNOOZED"}

print("now utc :", datetime.now(timezone.utc).isoformat(timespec="seconds"))
print()

for d in db.collection("medication_events").stream():
    e = {"id": d.id, **(d.to_dict() or {})}
    if e.get("elder_id") != ELDER:
        continue
    print(f"EVENT {e['id']}")
    for key in (
        "status", "medication_id", "scheduled_at", "local_time", "attempt",
        "max_attempts", "next_attempt_at", "reached_a_phone", "confirmed_at",
        "confirmed_source", "snooze_count", "escalated_at", "acknowledged_at",
    ):
        if key in e:
            print(f"   {key:18} {e[key]}")
    print(f"   -> would appear in the device queue: "
          f"{e.get('status') in OPEN}")
    print()
