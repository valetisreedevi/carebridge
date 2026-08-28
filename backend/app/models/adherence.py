"""How a dose is counted.

Every adherence figure CareBridge shows comes from here, because the honest
version of "how is she doing" needs two questions answered separately:

    did a reminder actually reach her, and what did she say?

Almost every product in this category collapses those into one number — doses
taken over doses scheduled — and a phone that was never set up then reads as a
woman ignoring her tablets. Splitting them is the whole point: REACH is ours to
answer for, OUTCOME is hers.
"""

from dataclasses import asdict, dataclass
from enum import Enum

from app.models.medication_event import MedicationEventStatus


class Reach(str, Enum):
    """Whether a reminder physically left the building."""

    DELIVERED = "DELIVERED"
    UNDELIVERED = "UNDELIVERED"
    NOT_YET_TRIED = "NOT_YET_TRIED"


class Outcome(str, Enum):
    """What came back."""

    TAKEN = "TAKEN"
    DECLINED = "DECLINED"
    NO_ANSWER = "NO_ANSWER"
    WAITING = "WAITING"
    CANCELLED = "CANCELLED"


# Statuses that mean nothing further is expected from the elder.
_OUTCOME_BY_STATUS = {
    MedicationEventStatus.TAKEN: Outcome.TAKEN,
    MedicationEventStatus.DECLINED: Outcome.DECLINED,
    MedicationEventStatus.ESCALATED: Outcome.NO_ANSWER,
    MedicationEventStatus.CANCELLED: Outcome.CANCELLED,
}


def classify_reach(event: dict) -> Reach:
    """A dose is only UNDELIVERED once we have actually tried and failed.

    A dose still ahead of its time has not failed at anything, and counting it
    against the household is how a dashboard cries wolf before breakfast.
    """
    if event.get("reached_a_phone"):
        return Reach.DELIVERED
    if event.get("attempt", 0) > 0:
        return Reach.UNDELIVERED
    return Reach.NOT_YET_TRIED


def classify_outcome(event: dict) -> Outcome:
    status = MedicationEventStatus(event["status"])
    return _OUTCOME_BY_STATUS.get(status, Outcome.WAITING)


def taken_on_trust(event: dict) -> bool:
    """Recorded on the family's word rather than the elder's own device.

    Kept countable, not hidden. A week that is only green because somebody
    ticked it off from another city is a different week, and a clinician
    reading this record deserves to be able to tell.
    """
    return (
        event.get("status") == MedicationEventStatus.TAKEN.value
        and event.get("confirmed_source") == "CAREGIVER"
    )


@dataclass(frozen=True)
class Ledger:
    """One window of doses, counted along both axes.

    REACH partitions the window exactly:

        scheduled == asked + unreachable + not_yet_due

    That identity is asserted in the tests. It is what lets the dashboard show
    three numbers that a family can add up themselves, instead of one number
    they have to trust.

    Cancelled doses sit outside the partition entirely. A medicine the family
    removed is not a dose anybody was asked to take, and leaving it in the
    denominator makes stopping a medicine look like a week of misses.
    """

    scheduled: int = 0

    # Reach — ours to answer for.
    asked: int = 0
    unreachable: int = 0
    not_yet_due: int = 0

    # Outcome — hers.
    taken: int = 0
    declined: int = 0
    no_answer: int = 0
    waiting: int = 0
    cancelled: int = 0

    # Qualifiers on the headline figures.
    taken_on_trust: int = 0
    unclear: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def balances(self) -> bool:
        return self.scheduled == self.asked + self.unreachable + self.not_yet_due


_REACH_FIELD = {
    Reach.DELIVERED: "asked",
    Reach.UNDELIVERED: "unreachable",
    Reach.NOT_YET_TRIED: "not_yet_due",
}

_OUTCOME_FIELD = {
    Outcome.TAKEN: "taken",
    Outcome.DECLINED: "declined",
    Outcome.NO_ANSWER: "no_answer",
    Outcome.WAITING: "waiting",
    Outcome.CANCELLED: "cancelled",
}


def build_ledger(events: list[dict]) -> Ledger:
    counts: dict[str, int] = {}

    for event in events:
        outcome_kind = classify_outcome(event)

        if outcome_kind is Outcome.CANCELLED:
            counts["cancelled"] = counts.get("cancelled", 0) + 1
            continue

        counts["scheduled"] = counts.get("scheduled", 0) + 1

        reach = _REACH_FIELD[classify_reach(event)]
        counts[reach] = counts.get(reach, 0) + 1

        outcome = _OUTCOME_FIELD[outcome_kind]
        counts[outcome] = counts.get(outcome, 0) + 1

        if taken_on_trust(event):
            counts["taken_on_trust"] = counts.get("taken_on_trust", 0) + 1

        if event.get("unclear_count", 0) > 0:
            counts["unclear"] = counts.get("unclear", 0) + 1

    return Ledger(**counts)
