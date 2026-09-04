"""READ-ONLY inventory of what is actually in Firestore.

Nothing here writes or deletes. It exists so that a cleanup can be decided
from the real data rather than from memory.
"""

from collections import defaultdict

from google.cloud import firestore

PROJECT = "carecompanion-506011"
db = firestore.Client(project=PROJECT)


def rows(collection):
    return [{"id": d.id, **(d.to_dict() or {})} for d in db.collection(collection).stream()]


elders = rows("elders")
medications = rows("medications")
devices = rows("devices")
events = rows("medication_events")

meds_by_elder = defaultdict(list)
for m in medications:
    meds_by_elder[m.get("elder_id")].append(m)

devices_by_elder = defaultdict(list)
for d in devices:
    for eid in d.get("elder_ids") or ([d["elder_id"]] if d.get("elder_id") else []):
        devices_by_elder[eid].append(d)

events_by_elder = defaultdict(int)
for e in events:
    events_by_elder[e.get("elder_id")] += 1

print(f"ELDERS: {len(elders)}   MEDICATIONS: {len(medications)}   "
      f"DEVICES: {len(devices)}   EVENTS: {len(events)}")
print("=" * 78)

for e in sorted(elders, key=lambda x: (x.get("name") or "", x["id"])):
    meds = meds_by_elder.get(e["id"], [])
    devs = devices_by_elder.get(e["id"], [])
    active_meds = [m for m in meds if m.get("active", True)]

    print(f"\nELDER {e['id']}  name={e.get('name')!r}  tz={e.get('timezone')}  "
          f"lang={e.get('preferred_language')}")
    print(f"  caregivers={e.get('caregiver_ids')}")
    print(f"  medications={len(meds)} ({len(active_meds)} active)  "
          f"devices={len(devs)}  events={events_by_elder.get(e['id'], 0)}")

    for m in meds:
        flags = []
        if m.get("photo_object_name"):
            flags.append("photo")
        if m.get("caregiver_audio_object_name"):
            flags.append("audio")
        if m.get("ends_on"):
            flags.append(f"course->{m['ends_on']}")
        print(f"    MED {m['id']}  {m.get('name')!r} {m.get('dose')!r} "
              f"times={m.get('schedule_times')} active={m.get('active', True)} "
              f"{' '.join(flags)}")

    for d in devs:
        print(f"    DEV {d['id']}  platform={d.get('platform')} "
              f"label={d.get('label')!r} active={d.get('active', True)} "
              f"last_seen={d.get('last_seen_at')}")

print("\n" + "=" * 78)
orphan_meds = [m for m in medications if m.get("elder_id") not in {e["id"] for e in elders}]
print(f"ORPHANED MEDICATIONS (elder_id points nowhere): {len(orphan_meds)}")
for m in orphan_meds:
    print(f"  {m['id']}  {m.get('name')!r}  elder_id={m.get('elder_id')}")
