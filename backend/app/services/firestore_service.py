from datetime import datetime, timezone
from functools import lru_cache

from google.cloud import firestore

from app.config import get_settings


@lru_cache
def get_db() -> firestore.Client:
    settings = get_settings()
    return firestore.Client(project=settings.gcp_project_id or None)


def _doc(snapshot) -> dict | None:
    if not snapshot.exists:
        return None
    return {"id": snapshot.id, **snapshot.to_dict()}


class FirestoreService:
    """Reads and writes for every collection except medication_events."""

    def __init__(self, db: firestore.Client | None = None):
        self.db = db or get_db()

    # ---------------- caregivers ----------------

    def upsert_caregiver(
        self,
        caregiver_id: str,
        name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
    ) -> dict:
        ref = self.db.collection("caregivers").document(caregiver_id)
        existing = ref.get()

        if existing.exists:
            updates = {
                key: value
                for key, value in (
                    ("name", name),
                    ("email", email),
                    ("phone", phone),
                )
                if value is not None
            }
            if updates:
                ref.update(updates)
            return _doc(ref.get())

        ref.set({
            "name": name,
            "email": email,
            "phone": phone,
            "fcm_tokens": [],
            "created_at": datetime.now(timezone.utc),
        })
        return _doc(ref.get())

    def get_caregiver(self, caregiver_id: str) -> dict | None:
        return _doc(self.db.collection("caregivers").document(caregiver_id).get())

    def add_caregiver_fcm_token(self, caregiver_id: str, token: str) -> None:
        self.db.collection("caregivers").document(caregiver_id).update({
            "fcm_tokens": firestore.ArrayUnion([token]),
        })

    # ---------------- elders ----------------

    def create_elder(
        self,
        name: str,
        caregiver_id: str,
        phone: str | None = None,
        preferred_language: str = "en",
        elder_timezone: str = "Asia/Kolkata",
    ) -> str:
        ref = self.db.collection("elders").document()
        ref.set({
            "name": name,
            "caregiver_id": caregiver_id,
            "caregiver_ids": [caregiver_id],
            "phone": phone,
            "preferred_language": preferred_language,
            "timezone": elder_timezone,
            "created_at": datetime.now(timezone.utc),
        })
        return ref.id

    def get_elder(self, elder_id: str) -> dict | None:
        return _doc(self.db.collection("elders").document(elder_id).get())

    def update_elder(self, elder_id: str, data: dict) -> None:
        self.db.collection("elders").document(elder_id).update({
            **data,
            "updated_at": datetime.now(timezone.utc),
        })

    def list_elders_for_caregiver(self, caregiver_id: str) -> list[dict]:
        query = self.db.collection("elders").where(
            filter=firestore.FieldFilter("caregiver_ids", "array_contains", caregiver_id)
        )
        return [{"id": d.id, **d.to_dict()} for d in query.stream()]

    def add_caregiver_to_elder(self, elder_id: str, caregiver_id: str) -> dict | None:
        elder = self.get_elder(elder_id)
        if not elder:
            return None

        caregivers = list(elder.get("caregiver_ids") or [])
        if caregiver_id not in caregivers:
            caregivers.append(caregiver_id)
            self.update_elder(elder_id, {"caregiver_ids": caregivers})

        return self.get_elder(elder_id)

    def remove_caregiver_from_elder(self, elder_id: str, caregiver_id: str) -> None:
        elder = self.get_elder(elder_id)
        if not elder:
            return

        caregivers = [c for c in (elder.get("caregiver_ids") or []) if c != caregiver_id]
        self.update_elder(elder_id, {"caregiver_ids": caregivers})

    # ---------------- invites ----------------

    def create_invite(
        self,
        code_hash: str,
        elder_id: str,
        created_by: str,
        expires_at: datetime,
    ) -> None:
        """Stores an invite under the hash of its code, never the code itself.

        The code is a credential: anyone holding it can read a family member's
        medication record. It is shown to the caregiver once and kept nowhere.
        """
        self.db.collection("caregiver_invites").document(code_hash).set({
            "elder_id": elder_id,
            "created_by": created_by,
            "expires_at": expires_at,
            "accepted_at": None,
            "accepted_by": None,
            "created_at": datetime.now(timezone.utc),
        })

    def get_invite(self, code_hash: str) -> dict | None:
        return _doc(
            self.db.collection("caregiver_invites").document(code_hash).get()
        )

    def accept_invite(self, code_hash: str, caregiver_id: str) -> None:
        self.db.collection("caregiver_invites").document(code_hash).update({
            "accepted_at": datetime.now(timezone.utc),
            "accepted_by": caregiver_id,
        })

    def caregiver_owns_elder(self, caregiver_id: str, elder_id: str) -> bool:
        elder = self.get_elder(elder_id)
        if not elder:
            return False
        return caregiver_id in (elder.get("caregiver_ids") or [])

    # ---------------- devices ----------------

    def register_device(
        self,
        elder_id: str,
        fcm_token: str,
        platform: str = "ANDROID",
    ) -> str:
        """Adds a person to a phone. It never replaces the people already on it.

        One document per token, so re-registering the same device is
        idempotent. The people it serves are a list: a phone on a shared side
        table belongs to a household, not to one person. Writing a single
        elder_id here used to mean pairing a second person silently unpaired the
        first, who then stopped receiving reminders with nothing to show for it.
        """
        ref = self.db.collection("devices").document(fcm_token[:200].replace("/", "_"))
        existing = _doc(ref.get()) or {}

        elder_ids = list(existing.get("elder_ids") or [])
        # Documents written before devices could be shared carry a single id.
        if existing.get("elder_id") and existing["elder_id"] not in elder_ids:
            elder_ids.append(existing["elder_id"])
        if elder_id not in elder_ids:
            elder_ids.append(elder_id)

        ref.set({
            "elder_ids": elder_ids,
            # Kept in step for any reader still expecting one id.
            "elder_id": elder_ids[0],
            "fcm_token": fcm_token,
            "platform": platform,
            "active": True,
            "updated_at": datetime.now(timezone.utc),
        })
        return ref.id

    def unregister_device(self, elder_id: str, fcm_token: str) -> None:
        """Takes one person off a phone, leaving anyone else on it alone."""
        ref = self.db.collection("devices").document(fcm_token[:200].replace("/", "_"))
        existing = _doc(ref.get())
        if not existing:
            return

        remaining = [e for e in (existing.get("elder_ids") or []) if e != elder_id]

        if not remaining:
            ref.update({"active": False, "elder_ids": [], "elder_id": None})
            return

        ref.update({"elder_ids": remaining, "elder_id": remaining[0]})

    def get_device_tokens(self, elder_id: str) -> list[str]:
        queries = (
            self.db.collection("devices").where(
                filter=firestore.FieldFilter("elder_ids", "array_contains", elder_id)
            ),
            # Devices registered before sharing existed.
            self.db.collection("devices").where(
                filter=firestore.FieldFilter("elder_id", "==", elder_id)
            ),
        )

        tokens = []
        for query in queries:
            for snapshot in query.stream():
                data = snapshot.to_dict()
                if data.get("active") and data["fcm_token"] not in tokens:
                    tokens.append(data["fcm_token"])

        return tokens

    # ---------------- medications ----------------

    def create_medication(self, data: dict) -> str:
        ref = self.db.collection("medications").document()
        ref.set({
            **data,
            "active": data.get("active", True),
            "created_at": datetime.now(timezone.utc),
        })
        return ref.id

    def get_medication(self, medication_id: str) -> dict | None:
        return _doc(self.db.collection("medications").document(medication_id).get())

    def update_medication(self, medication_id: str, data: dict) -> None:
        self.db.collection("medications").document(medication_id).update(data)

    def delete_medication(self, medication_id: str) -> None:
        # Soft delete: past medication_events keep pointing at this document.
        self.db.collection("medications").document(medication_id).update({
            "active": False,
            "deactivated_at": datetime.now(timezone.utc),
        })

    def list_medications_for_elder(
        self,
        elder_id: str,
        active_only: bool = True,
    ) -> list[dict]:
        query = self.db.collection("medications").where(
            filter=firestore.FieldFilter("elder_id", "==", elder_id)
        )
        medications = [{"id": d.id, **d.to_dict()} for d in query.stream()]
        if active_only:
            medications = [m for m in medications if m.get("active")]
        return sorted(medications, key=lambda m: m.get("schedule_time", ""))

    def list_active_medications(self) -> list[dict]:
        query = self.db.collection("medications").where(
            filter=firestore.FieldFilter("active", "==", True)
        )
        return [{"id": d.id, **d.to_dict()} for d in query.stream()]
