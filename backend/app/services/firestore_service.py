import hashlib
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


def _device_doc_id(fcm_token: str) -> str:
    """One document per phone, keyed by a hash of its token.

    The token itself was used, truncated to 200 characters and with slashes
    swapped out. Two tokens sharing a prefix would then collide into one
    document, and because registration writes rather than merges, a phone
    could silently be reassigned to another household.
    """
    return hashlib.sha256(fcm_token.encode()).hexdigest()


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

    # ---------------- elder pairing codes ----------------

    def create_pairing_code(
        self,
        code_hash: str,
        elder_id: str,
        created_by: str,
        expires_at: datetime,
    ) -> None:
        """Stores a phone-pairing code under its hash, never as the code.

        Same treatment as a caregiver invite, for the same reason: whoever
        redeems it can read a family member's medication record.
        """
        self.db.collection("elder_pairing_codes").document(code_hash).set({
            "elder_id": elder_id,
            "created_by": created_by,
            "expires_at": expires_at,
            "redeemed_at": None,
            "created_at": datetime.now(timezone.utc),
        })

    def claim_pairing_code(self, code_hash: str) -> dict | None:
        """Takes a code if it is still good, atomically, and returns it.

        One transaction rather than check-then-write: two phones typing the
        same code at once must not both end up paired, and a code that has
        been spent is spent. Returns None for unknown, already redeemed, and
        expired alike — the caller cannot tell them apart, and neither can
        anyone probing the endpoint.
        """
        ref = self.db.collection("elder_pairing_codes").document(code_hash)

        @firestore.transactional
        def claim(transaction):
            snapshot = ref.get(transaction=transaction)
            if not snapshot.exists:
                return None

            data = snapshot.to_dict()
            if data.get("redeemed_at"):
                return None

            expires_at = data["expires_at"]
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at < datetime.now(timezone.utc):
                return None

            transaction.update(ref, {"redeemed_at": datetime.now(timezone.utc)})
            return {"id": code_hash, **data}

        return claim(self.db.transaction())

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
        label: str | None = None,
    ) -> str:
        """Adds a person to a phone. It never replaces the people already on it.

        One document per token, so re-registering the same device is
        idempotent. The people it serves are a list: a phone on a shared side
        table belongs to a household, not to one person. Writing a single
        elder_id here used to mean pairing a second person silently unpaired the
        first, who then stopped receiving reminders with nothing to show for it.
        """
        ref = self.db.collection("devices").document(_device_doc_id(fcm_token))
        existing = _doc(ref.get()) or {}

        elder_ids = list(existing.get("elder_ids") or [])
        # Documents written before devices could be shared carry a single id.
        if existing.get("elder_id") and existing["elder_id"] not in elder_ids:
            elder_ids.append(existing["elder_id"])
        if elder_id not in elder_ids:
            elder_ids.append(elder_id)

        now = datetime.now(timezone.utc)

        ref.set({
            "elder_ids": elder_ids,
            # Kept in step for any reader still expecting one id.
            "elder_id": elder_ids[0],
            "fcm_token": fcm_token,
            "platform": platform,
            "label": label or existing.get("label"),
            "active": True,
            # When the family first set this phone up, kept across
            # re-registrations so the dashboard can say how long it has been
            # in service rather than how recently the page was opened.
            "paired_at": existing.get("paired_at") or now,
            "last_seen_at": now,
            "updated_at": now,
        })
        return ref.id

    def list_devices_for_elder(self, elder_id: str) -> list[dict]:
        """The phones a caregiver can see, newest contact first.

        Never returns the FCM token. It is the address of a person's phone and
        the dashboard has no use for it — what a family needs to know is
        whether a phone is set up and when it last checked in.
        """
        seen, devices = set(), []

        for query in self._device_queries(elder_id):
            for snapshot in query.stream():
                if snapshot.id in seen:
                    continue
                seen.add(snapshot.id)

                data = snapshot.to_dict()
                if not data.get("active"):
                    continue

                devices.append({
                    "device_id": snapshot.id,
                    "platform": data.get("platform"),
                    "label": data.get("label"),
                    "paired_at": data.get("paired_at"),
                    "last_seen_at": data.get("last_seen_at"),
                    "shared_with": max(len(data.get("elder_ids") or []) - 1, 0),
                })

        return sorted(
            devices,
            key=lambda d: d.get("last_seen_at") or d.get("paired_at") or "",
            reverse=True,
        )

    def unregister_device(self, elder_id: str, fcm_token: str) -> None:
        """Takes one person off a phone, leaving anyone else on it alone."""
        ref = self.db.collection("devices").document(_device_doc_id(fcm_token))
        existing = _doc(ref.get())
        if not existing:
            return

        remaining = [e for e in (existing.get("elder_ids") or []) if e != elder_id]

        if not remaining:
            ref.update({"active": False, "elder_ids": [], "elder_id": None})
            return

        ref.update({"elder_ids": remaining, "elder_id": remaining[0]})

    def deactivate_devices_for_elder(self, elder_id: str) -> int:
        """Takes one elder off every phone they are paired to.

        The counterpart to revoking their Firebase sessions: that stops the
        devices reading, this stops CareBridge writing to them. Anyone else on
        a shared handset stays paired.
        """
        seen: set[str] = set()

        for query in self._device_queries(elder_id):
            for snapshot in query.stream():
                if snapshot.id in seen:
                    continue
                seen.add(snapshot.id)

                data = snapshot.to_dict()
                remaining = [
                    e for e in (data.get("elder_ids") or []) if e != elder_id
                ]
                ref = self.db.collection("devices").document(snapshot.id)

                if remaining:
                    ref.update({"elder_ids": remaining, "elder_id": remaining[0]})
                else:
                    ref.update({"active": False, "elder_ids": [], "elder_id": None})

        return len(seen)

    def _device_queries(self, elder_id: str):
        return (
            self.db.collection("devices").where(
                filter=firestore.FieldFilter("elder_ids", "array_contains", elder_id)
            ),
            # Devices registered before sharing existed.
            self.db.collection("devices").where(
                filter=firestore.FieldFilter("elder_id", "==", elder_id)
            ),
        )

    def get_device_targets(self, elder_id: str) -> list[dict]:
        """The phones to push to, each with the kind of client it is.

        A browser and a native Android app need differently shaped messages —
        an Android app that is asleep never sees a message carrying a
        notification block, because the system tray swallows it before any of
        the app's own code runs. The sender cannot tell the two apart from a
        bare token, so the platform has to travel with it.
        """
        targets, seen = [], set()

        for query in self._device_queries(elder_id):
            for snapshot in query.stream():
                data = snapshot.to_dict()
                token = data.get("fcm_token")

                if not data.get("active") or not token or token in seen:
                    continue

                seen.add(token)
                targets.append({
                    "fcm_token": token,
                    "platform": data.get("platform"),
                })

        return targets

    def get_device_tokens(self, elder_id: str) -> list[str]:
        return [target["fcm_token"] for target in self.get_device_targets(elder_id)]

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
