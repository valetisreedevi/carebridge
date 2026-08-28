"""Counting a dose honestly.

The whole point of the ledger is that a family can add the numbers up
themselves. If reach stops partitioning the window, the dashboard is back to
one number nobody can check — which is the failure mode this replaced.
"""

from datetime import datetime, timedelta, timezone

from app.models.adherence import (
    Outcome,
    Reach,
    build_ledger,
    classify_outcome,
    classify_reach,
    taken_on_trust,
)
from app.services.adherence_service import median_latency, minutes_to_taken

EIGHT_AM = datetime(2026, 8, 27, 2, 30, tzinfo=timezone.utc)


def _event(status="PENDING", reached=None, attempt=0, **extra):
    return {
        "status": status,
        "attempt": attempt,
        "scheduled_at": EIGHT_AM,
        **({"reached_a_phone": reached} if reached is not None else {}),
        **extra,
    }


def test_a_dose_still_to_come_has_not_failed_at_anything():
    assert classify_reach(_event()) is Reach.NOT_YET_TRIED


def test_a_dose_we_tried_and_could_not_deliver_is_undelivered():
    assert classify_reach(_event(attempt=2, reached=False)) is Reach.UNDELIVERED


def test_one_delivery_makes_the_dose_asked_about():
    assert classify_reach(_event(attempt=1, reached=True)) is Reach.DELIVERED


def test_an_escalated_dose_counts_as_no_answer_not_as_refused():
    """Silence is not a refusal, and the record must not turn it into one."""
    assert classify_outcome(_event("ESCALATED")) is Outcome.NO_ANSWER
    assert classify_outcome(_event("DECLINED")) is Outcome.DECLINED


def test_reach_partitions_the_window_exactly():
    ledger = build_ledger([
        _event("TAKEN", reached=True, attempt=1),
        _event("TAKEN", reached=True, attempt=1),
        _event("ESCALATED", reached=True, attempt=2),
        _event("ESCALATED", reached=False, attempt=2),
        _event("DECLINED", reached=True, attempt=1),
        _event(),
    ])

    assert ledger.scheduled == 6
    assert ledger.asked == 4
    assert ledger.unreachable == 1
    assert ledger.not_yet_due == 1
    assert ledger.balances


def test_a_removed_medicine_leaves_the_denominator_alone():
    """Stopping a medicine must not read as a week of misses."""
    ledger = build_ledger([
        _event("TAKEN", reached=True, attempt=1),
        _event("CANCELLED", reached=False, attempt=1),
    ])

    assert ledger.scheduled == 1
    assert ledger.cancelled == 1
    assert ledger.balances


def test_a_dose_recorded_by_the_family_is_still_countable_as_such():
    on_trust = _event("TAKEN", reached=True, attempt=1, confirmed_source="CAREGIVER")
    herself = _event("TAKEN", reached=True, attempt=1, confirmed_source="ELDER")

    assert taken_on_trust(on_trust)
    assert not taken_on_trust(herself)

    ledger = build_ledger([on_trust, herself])
    assert ledger.taken == 2
    assert ledger.taken_on_trust == 1


def test_a_dose_nobody_could_interpret_is_counted_once_however_many_replies():
    ledger = build_ledger([_event("ESCALATED", reached=True, attempt=2, unclear_count=3)])
    assert ledger.unclear == 1


def test_latency_ignores_doses_the_family_ticked_off():
    """A dashboard tick is stamped when somebody got round to it.

    Counting that as how long the tablet took would flatten the one number
    that moves before anything is actually missed.
    """
    herself = _event(
        "TAKEN",
        reached=True,
        attempt=1,
        confirmed_source="ELDER",
        confirmed_at=EIGHT_AM + timedelta(minutes=12),
    )
    from_afar = _event(
        "TAKEN",
        reached=True,
        attempt=1,
        confirmed_source="CAREGIVER",
        confirmed_at=EIGHT_AM + timedelta(hours=9),
    )

    assert minutes_to_taken(herself) == 12
    assert minutes_to_taken(from_afar) is None
    assert median_latency([herself, from_afar]) == 12


def test_a_week_with_nothing_delivered_reports_no_adherence_rather_than_zero():
    """Zero percent is a claim about her. No data is a claim about us."""
    from app.services.adherence_service import adherence_of_asked

    ledger = build_ledger([_event("ESCALATED", reached=False, attempt=2)])

    assert ledger.asked == 0
    assert adherence_of_asked(ledger) is None
