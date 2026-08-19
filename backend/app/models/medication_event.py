from enum import Enum


class MedicationEventStatus(str, Enum):
    PENDING = "PENDING"
    REMINDER_SENT = "REMINDER_SENT"
    SNOOZED = "SNOOZED"
    TAKEN = "TAKEN"
    DECLINED = "DECLINED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


TERMINAL_STATUSES = frozenset({
    MedicationEventStatus.TAKEN,
    MedicationEventStatus.DECLINED,
    MedicationEventStatus.ESCALATED,
    MedicationEventStatus.CANCELLED,
})

# The backend is the only component allowed to move an event between states.
# The agent may request a transition through a tool; the transition itself is
# validated here.
ALLOWED_TRANSITIONS: dict[MedicationEventStatus, frozenset[MedicationEventStatus]] = {
    MedicationEventStatus.PENDING: frozenset({
        MedicationEventStatus.REMINDER_SENT,
        MedicationEventStatus.CANCELLED,
    }),
    MedicationEventStatus.REMINDER_SENT: frozenset({
        MedicationEventStatus.TAKEN,
        MedicationEventStatus.DECLINED,
        MedicationEventStatus.SNOOZED,
        MedicationEventStatus.REMINDER_SENT,
        MedicationEventStatus.ESCALATED,
        MedicationEventStatus.CANCELLED,
    }),
    MedicationEventStatus.SNOOZED: frozenset({
        MedicationEventStatus.REMINDER_SENT,
        MedicationEventStatus.TAKEN,
        MedicationEventStatus.DECLINED,
        MedicationEventStatus.ESCALATED,
        MedicationEventStatus.CANCELLED,
    }),
    MedicationEventStatus.TAKEN: frozenset(),
    MedicationEventStatus.DECLINED: frozenset(),
    MedicationEventStatus.ESCALATED: frozenset(),
    MedicationEventStatus.CANCELLED: frozenset(),
}


class InvalidTransition(Exception):
    def __init__(
        self,
        current: MedicationEventStatus,
        requested: MedicationEventStatus,
    ):
        super().__init__(
            f"Cannot move medication event from {current.value} to {requested.value}"
        )
        self.current = current
        self.requested = requested


def can_transition(
    current: MedicationEventStatus,
    requested: MedicationEventStatus,
) -> bool:
    return requested in ALLOWED_TRANSITIONS[current]
