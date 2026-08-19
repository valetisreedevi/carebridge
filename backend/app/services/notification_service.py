import logging
from datetime import datetime, timezone

from app.services.firestore_service import FirestoreService, get_db

logger = logging.getLogger(__name__)

try:
    import firebase_admin
    from firebase_admin import messaging

    if not firebase_admin._apps:
        firebase_admin.initialize_app()
    FCM_AVAILABLE = True
except Exception as exc:  # firebase-admin missing or no credentials
    logger.warning("FCM unavailable, notifications will be logged only: %s", exc)
    FCM_AVAILABLE = False


class NotificationService:
    """Delivers reminders to elder devices and escalations to caregivers.

    Every dispatch is also written to the notifications collection, which is
    what the web clients poll. That makes the whole flow demonstrable even
    when FCM has no registered device.
    """

    def __init__(self, db=None):
        self.db = db or get_db()
        self.firestore = FirestoreService(self.db)

    def _record(self, payload: dict) -> str:
        ref = self.db.collection("notifications").document()
        ref.set({**payload, "created_at": datetime.now(timezone.utc)})
        return ref.id

    def _push(self, tokens: list[str], title: str, body: str, data: dict) -> int:
        if not FCM_AVAILABLE or not tokens:
            return 0

        message = messaging.MulticastMessage(
            tokens=tokens,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in data.items()},
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id="carebridge_reminders",
                    priority="max",
                    default_sound=True,
                    visibility="public",
                ),
            ),
        )
        try:
            response = messaging.send_each_for_multicast(message)
            return response.success_count
        except Exception as exc:
            logger.exception("FCM send failed: %s", exc)
            return 0

    def send_reminder(
        self,
        elder: dict,
        medication: dict,
        event: dict,
    ) -> dict:
        """Payload stays minimal; the device fetches the event from the API."""
        data = {
            "type": "MEDICATION_REMINDER",
            "event_id": event["id"],
            "elder_id": elder["id"],
        }

        tokens = self.firestore.get_device_tokens(elder["id"])
        delivered = self._push(
            tokens,
            title="Medicine time",
            body=f"{medication['name']} - {medication['dose']}",
            data=data,
        )

        notification_id = self._record({
            **data,
            "medication_id": medication["id"],
            "attempt": event.get("attempt", 0) + 1,
            "audience": "ELDER",
            "delivered_to": delivered,
            "device_count": len(tokens),
        })

        logger.info(
            "Reminder for %s (%s) attempt %s -> %s device(s)",
            elder["name"],
            medication["name"],
            event.get("attempt", 0) + 1,
            delivered,
        )
        return {"notification_id": notification_id, "delivered_to": delivered}

    def notify_caregiver(
        self,
        elder: dict,
        medication: dict,
        event: dict,
        reason: str,
        message: str,
    ) -> dict:
        caregiver_ids = elder.get("caregiver_ids") or []

        tokens: list[str] = []
        for caregiver_id in caregiver_ids:
            caregiver = self.firestore.get_caregiver(caregiver_id)
            if caregiver:
                tokens.extend(caregiver.get("fcm_tokens") or [])

        data = {
            "type": "CAREGIVER_ALERT",
            "reason": reason,
            "event_id": event["id"],
            "elder_id": elder["id"],
        }

        delivered = self._push(tokens, title="CareBridge", body=message, data=data)

        notification_id = self._record({
            **data,
            "medication_id": medication.get("id"),
            "audience": "CAREGIVER",
            "caregiver_ids": caregiver_ids,
            "message": message,
            "delivered_to": delivered,
            "read": False,
        })

        logger.info("Caregiver alert (%s): %s", reason, message)
        return {"notification_id": notification_id, "delivered_to": delivered}

    def list_for_caregiver(self, caregiver_id: str, limit: int = 50) -> list[dict]:
        from google.cloud import firestore as fs

        query = self.db.collection("notifications").where(
            filter=fs.FieldFilter("caregiver_ids", "array_contains", caregiver_id)
        )
        alerts = [
            {"id": d.id, **d.to_dict()}
            for d in query.stream()
            if d.to_dict().get("audience") == "CAREGIVER"
        ]
        return sorted(alerts, key=lambda a: a["created_at"], reverse=True)[:limit]
