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

    def list_elders_for_caregiver(self, caregiver_id: str) -> list[dict]:
        query = self.db.collection("elders").where(
            filter=firestore.FieldFilter("caregiver_ids", "array_contains", caregiver_id)
        )
        return [{"id": d.id, **d.to_dict()} for d in query.stream()]

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
        # One document per token so re-registering the same device is idempotent.
        ref = self.db.collection("devices").document(fcm_token[:200].replace("/", "_"))
        ref.set({
            "elder_id": elder_id,
            "fcm_token": fcm_token,
            "platform": platform,
            "active": True,
            "updated_at": datetime.now(timezone.utc),
        })
        return ref.id

    def get_device_tokens(self, elder_id: str) -> list[str]:
        query = self.db.collection("devices").where(
            filter=firestore.FieldFilter("elder_id", "==", elder_id)
        )
        return [
            d.to_dict()["fcm_token"]
            for d in query.stream()
            if d.to_dict().get("active")
        ]

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
