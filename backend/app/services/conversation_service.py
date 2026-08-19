from datetime import datetime, timezone

from google.cloud import firestore

from app.services.firestore_service import get_db


class ConversationService:
    """Transcript of what the elder said and how the agent answered.

    One session per (elder, event) so a snooze and the follow-up reminder
    share context.
    """

    def __init__(self, db=None):
        self.db = db or get_db()

    def get_or_create_session(self, elder_id: str, event_id: str | None) -> str:
        session_id = f"{elder_id}_{event_id or 'general'}"
        ref = self.db.collection("conversations").document(session_id)

        if not ref.get().exists:
            ref.set({
                "elder_id": elder_id,
                "event_id": event_id,
                "created_at": datetime.now(timezone.utc),
            })
        return session_id

    def add_message(
        self,
        session_id: str,
        role: str,
        text: str,
        intent: str | None = None,
        tool_calls: list[str] | None = None,
    ) -> None:
        self.db.collection("conversations").document(session_id).collection(
            "messages"
        ).add({
            "role": role,
            "text": text,
            "intent": intent,
            "tool_calls": tool_calls or [],
            "timestamp": datetime.now(timezone.utc),
        })

    def get_messages(self, session_id: str, limit: int = 50) -> list[dict]:
        query = (
            self.db.collection("conversations")
            .document(session_id)
            .collection("messages")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        messages = [d.to_dict() for d in query.stream()]
        return list(reversed(messages))
