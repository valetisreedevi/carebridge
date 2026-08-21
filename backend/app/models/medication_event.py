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
    # ESCALATED is the end of the dose but not of the story: the escalation
    # ladder keeps working through ways to reach the caregiver, so the event
    # stays live and removing the medicine has to be able to close it.
    #
    # A caregiver marking it taken is NOT here. That is an override of what the
    # device knows, and it is guarded separately in confirm_by_caregiver so it
    # stays visible rather than becoming a hole in this map.
    MedicationEventStatus.ESCALATED: frozenset({MedicationEventStatus.CANCELLED}),
    MedicationEventStatus.CANCELLED: frozenset(),
}


# What a caregiver may vouch for. A dose the elder already answered is not on
# the list: TAKEN needs no help, and DECLINED means they said no — overriding
# that from another room is not a correction.
CAREGIVER_CONFIRMABLE = frozenset({
    MedicationEventStatus.PENDING,
    MedicationEventStatus.REMINDER_SENT,
    MedicationEventStatus.SNOOZED,
    MedicationEventStatus.ESCALATED,
})


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
