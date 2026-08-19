from functools import lru_cache

from app.services.conversation_service import ConversationService
from app.services.firestore_service import FirestoreService
from app.services.medication_event_service import MedicationEventService
from app.services.notification_service import NotificationService
from app.services.reminder_service import ReminderService
from app.services.storage_service import StorageService


@lru_cache
def firestore_service() -> FirestoreService:
    return FirestoreService()


@lru_cache
def event_service() -> MedicationEventService:
    return MedicationEventService()


@lru_cache
def notification_service() -> NotificationService:
    return NotificationService()


@lru_cache
def reminder_service() -> ReminderService:
    return ReminderService()


@lru_cache
def storage_service() -> StorageService:
    return StorageService()


@lru_cache
def conversation_service() -> ConversationService:
    return ConversationService()
