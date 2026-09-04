"""Clear the test wreckage out of Firestore and give Amma a clean slate.

Backs everything up to JSON before touching anything. Deletes only the ids
listed explicitly below - nothing is inferred at runtime, so what runs is
exactly what was agreed.

KEPT ON PURPOSE:
  6nQXfpLKzOywKnM3jyHH  the real Amma. Her paired Oppo hangs off this document;
                        deleting it would cost a re-pair before the demo.
  X6JAUj6w707qyvmUBenm  the real Nanna.
  the three Amma docs owned by real Firebase UIDs, which may be second accounts.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import firestore

PROJECT = "carecompanion-506011"
db = firestore.Client(project=PROJECT)

REAL_AMMA = "6nQXfpLKzOywKnM3jyHH"
REAL_NANNA = "X6JAUj6w707qyvmUBenm"

# Test wreckage: every one of these is owned by a synthetic caregiver id
# (escalation-check, deploy-check, e2e-caregiver, caregiver-<hex>), plus one
# elder with no timezone and no caregivers at all.
DELETE_ELDERS = [
    "9vbv81X14BglnnKLWwck",  # escalation-check
    "jjec0DxckVKnY0WJdT2K",  # escalation-check
    "puUG1XZhK3qDqK3dtcC1",  # escalation-check
    "NIuci0cRUIGaLAEHN68R",  # deploy-check
    "mlO90kDAiaUtntydSRqp",  # deploy-check
    "aj7IfK1QbqvDJeek6VxL",  # e2e-caregiver
    "bq4FBgdnq9acuAZfjNb2",  # e2e-caregiver
    "gcRDlQUkVCfvtQIM9NOu",  # e2e-caregiver
    "YqkaOjCushVgJ8OJBmzX",  # caregiver-ca4c8d79
    "GV5h6lNsQJv5cnGT80R5",  # caregiver-4f08f768, a second "Nanna"
    "XqxWY2REaj1mapz3282p",  # "Lakshmi": no timezone, no caregivers
]

ORPHAN_MEDICATIONS = [
    "Fp2wkT0bBWf2kFwxhwHV",  # elder_id is the literal string YOUR_ELDER_ID
]

COLLECTIONS = ["elders", "medications", "devices", "medication_events",
               "notifications", "caregivers"]


def rows(name):
    return [{"id": d.id, **(d.to_dict() or {})} for d in db.collection(name).stream()]


def backup(snapshot: dict) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = Path(__file__).parent / f"firestore-backup-{stamp}.json"
    path.write_text(json.dumps(snapshot, indent=2, default=str), encoding="utf-8")
    return path


def main(apply: bool) -> None:
    snapshot = {name: rows(name) for name in COLLECTIONS}
    path = backup(snapshot)
    print(f"backup written: {path.name} "
          f"({sum(len(v) for v in snapshot.values())} documents)\n")

    doomed_elders = set(DELETE_ELDERS)

    # Medications: everything belonging to a doomed elder, everything on the
    # real Amma (the clean slate that was asked for), and the placeholder.
    med_ids = [
        m["id"] for m in snapshot["medications"]
        if m.get("elder_id") in doomed_elders
        or m.get("elder_id") == REAL_AMMA
        or m["id"] in ORPHAN_MEDICATIONS
    ]

    # Events: Amma's history, and anything hanging off a doomed elder.
    event_ids = [
        e["id"] for e in snapshot["medication_events"]
        if e.get("elder_id") in doomed_elders or e.get("elder_id") == REAL_AMMA
    ]

    # Devices: only ones that reference NOTHING but doomed elders. The Oppo is
    # attached to the real Amma and must survive untouched.
    device_ids = []
    for d in snapshot["devices"]:
        linked = set(d.get("elder_ids") or ([d["elder_id"]] if d.get("elder_id") else []))
        if linked and linked.issubset(doomed_elders):
            device_ids.append(d["id"])

    plan = {
        "elders": sorted(doomed_elders),
        "medications": med_ids,
        "medication_events": event_ids,
        "devices": device_ids,
    }

    for collection, ids in plan.items():
        print(f"{collection}: {len(ids)} to delete")

    kept_devices = [d["id"][:12] for d in snapshot["devices"] if d["id"] not in device_ids]
    print(f"\ndevices KEPT: {kept_devices}")
    print(f"elders KEPT: {sorted({e['id'] for e in snapshot['elders']} - doomed_elders)}")

    if not apply:
        print("\nDRY RUN - nothing deleted. Re-run with --apply to commit.")
        return

    print()
    for collection, ids in plan.items():
        for doc_id in ids:
            db.collection(collection).document(doc_id).delete()
        print(f"deleted {len(ids)} from {collection}")

    after = {name: rows(name) for name in ["elders", "medications", "medication_events"]}
    print("\nAFTER: " + "  ".join(f"{k}={len(v)}" for k, v in after.items()))


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
