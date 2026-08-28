"""Turns the event log into figures, deterministically.

Nothing here calls a model. Every number a caregiver reads, and every number
the analyst agent is later asked to phrase, is computed in this file with
ordinary arithmetic. The agent writes the sentence; it never works out what the
sentence should say. A bad generation can make the wording clumsy. It cannot
make the adherence rate wrong.
"""

import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.adherence import Ledger, build_ledger
from app.models.medication_event import MedicationEventStatus
from app.services.firestore_service import FirestoreService, get_db
from app.services.medication_event_service import MedicationEventService

# Where one part of the day ends and the next begins, in the elder's own clock.
MORNING_ENDS = 12
AFTERNOON_ENDS = 17

# How much of a change is worth telling a family about. Under this it is noise,
# and a weekly note that reacts to noise is one nobody finishes reading.
MATERIAL_SHIFT = 0.15

# How many weeks before this one count as "usually".
BASELINE_WEEKS = 3


def elder_zone(elder: dict) -> ZoneInfo:
    try:
        return ZoneInfo(elder.get("timezone") or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def part_of_day(moment: datetime, tz: ZoneInfo) -> str:
    hour = moment.astimezone(tz).hour
    if hour < MORNING_ENDS:
        return "morning"
    if hour < AFTERNOON_ENDS:
        return "afternoon"
    return "evening"


def minutes_to_taken(event: dict) -> float | None:
    """How long the dose took, when the elder answered for it themselves.

    A dose the family ticked off from another city has no meaningful latency —
    it is stamped when somebody got round to the dashboard, not when the tablet
    was swallowed — so it is left out rather than quietly flattening the median.
    """
    if event.get("status") != MedicationEventStatus.TAKEN.value:
        return None
    if event.get("confirmed_source") == "CAREGIVER":
        return None

    confirmed = event.get("confirmed_at")
    scheduled = event.get("scheduled_at")
    if not confirmed or not scheduled:
        return None

    return max(0.0, (confirmed - scheduled).total_seconds() / 60)


def median_latency(events: list[dict]) -> float | None:
    """The number that moves first.

    Adherence rate is what everyone reports and it is the last thing to fall:
    somebody beginning to struggle still takes the tablet, just later and
    later. The median wait from scheduled to confirmed shows that drift weeks
    before a single dose is actually missed.
    """
    samples = [m for m in (minutes_to_taken(e) for e in events) if m is not None]
    return round(statistics.median(samples), 1) if samples else None


def adherence_of_asked(ledger: Ledger) -> float | None:
    """Taken as a share of the doses we actually managed to ask about.

    Deliberately not over everything scheduled. Dividing by doses that were
    never delivered measures our own plumbing and reports the result as her
    behaviour.
    """
    return round(ledger.taken / ledger.asked, 3) if ledger.asked else None


class AdherenceService:

    def __init__(self, db=None):
        self.db = db or get_db()
        self.firestore = FirestoreService(self.db)
        self.events = MedicationEventService(self.db)

    # ---------------- windows ----------------

    def events_between(
        self,
        elder_id: str,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        return self.events.list_events_for_elder_between(elder_id, start, end)

    def ledger_between(
        self,
        elder_id: str,
        start: datetime,
        end: datetime,
    ) -> Ledger:
        return build_ledger(self.events_between(elder_id, start, end))

    def _week_bounds(
        self,
        tz: ZoneInfo,
        weeks_ago: int = 0,
    ) -> tuple[datetime, datetime]:
        midnight = datetime.now(tz).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = midnight + timedelta(days=1) - timedelta(weeks=weeks_ago)
        return end - timedelta(days=7), end

    # ---------------- one dose, for an escalation ----------------

    def dose_brief(self, event: dict, elder: dict, medication: dict) -> dict:
        """Everything known about the dose that just went unanswered.

        Handed to the analyst as facts. The escalation has already been decided
        and the first alert already sent by the time this is built — this only
        supplies words for the slower channel that follows.
        """
        tz = elder_zone(elder)
        scheduled = event["scheduled_at"]

        return {
            "elder_name": elder.get("name"),
            "medication_name": medication.get("name"),
            "scheduled_local": scheduled.astimezone(tz).strftime("%I:%M %p").lstrip("0"),
            "part_of_day": part_of_day(scheduled, tz),
            "reminder_attempts": event.get("attempt", 0),
            "reached_a_phone": bool(event.get("reached_a_phone")),
            "times_put_off": event.get("snooze_count", 0),
            "replies_not_understood": event.get("unclear_count", 0),
            "reason": event.get("escalation_reason") or "NOT_CONFIRMED",
            "same_dose_last_14_days": self._same_dose_history(event, elder, tz),
        }

    def _same_dose_history(self, event: dict, elder: dict, tz: ZoneInfo) -> dict:
        """How this particular slot — this medicine, this time — usually goes.

        "She missed her tablet" and "she has missed this evening tablet four
        times this fortnight" are different messages to receive, and only the
        second tells a family whether to worry tonight or on Monday.
        """
        end = event["scheduled_at"]
        window = self.events_between(elder["id"], end - timedelta(days=14), end)

        local_time = end.astimezone(tz).strftime("%H:%M")
        same_slot = [
            e
            for e in window
            if e["medication_id"] == event["medication_id"]
            and e["scheduled_at"].astimezone(tz).strftime("%H:%M") == local_time
        ]

        ledger = build_ledger(same_slot)
        return {
            "doses": ledger.scheduled,
            "asked": ledger.asked,
            "taken": ledger.taken,
            "unanswered": ledger.no_answer,
            "never_delivered": ledger.unreachable,
        }

    # ---------------- a week, for the family note ----------------

    def weekly_brief(self, elder_id: str) -> dict:
        """This week beside the three before it.

        Both halves are computed here. The analyst is handed the pair and asked
        which way things moved; it is never asked to work out either number, so
        the worst a bad generation can do is describe a real change clumsily.
        """
        elder = self.firestore.get_elder(elder_id) or {}
        tz = elder_zone(elder)

        start, end = self._week_bounds(tz)
        this_week = self.events_between(elder_id, start, end)
        ledger = build_ledger(this_week)

        baseline_start = start - timedelta(weeks=BASELINE_WEEKS)
        baseline_events = self.events_between(elder_id, baseline_start, start)
        baseline = build_ledger(baseline_events)

        return {
            "elder_name": elder.get("name"),
            "week_starting": start.date().isoformat(),
            "this_week": {
                **ledger.to_dict(),
                "adherence_of_asked": adherence_of_asked(ledger),
                "median_minutes_to_taken": median_latency(this_week),
                "by_part_of_day": self._by_part_of_day(this_week, tz),
            },
            "usual": {
                **baseline.to_dict(),
                "weeks_counted": BASELINE_WEEKS,
                "adherence_of_asked": adherence_of_asked(baseline),
                "median_minutes_to_taken": median_latency(baseline_events),
                "by_part_of_day": self._by_part_of_day(baseline_events, tz),
            },
            "what_changed": self._what_changed(
                this_week, ledger, baseline_events, baseline, tz
            ),
        }

    def _by_part_of_day(self, events: list[dict], tz: ZoneInfo) -> dict:
        buckets: dict[str, list[dict]] = {
            "morning": [],
            "afternoon": [],
            "evening": [],
        }
        for event in events:
            buckets[part_of_day(event["scheduled_at"], tz)].append(event)

        summary = {}
        for name, group in buckets.items():
            ledger = build_ledger(group)
            summary[name] = {
                "scheduled": ledger.scheduled,
                "asked": ledger.asked,
                "taken": ledger.taken,
                "adherence_of_asked": adherence_of_asked(ledger),
            }
        return summary

    def _what_changed(
        self,
        this_week: list[dict],
        ledger: Ledger,
        baseline_events: list[dict],
        baseline: Ledger,
        tz: ZoneInfo,
    ) -> list[dict]:
        """Differences worth a sentence, already decided here.

        An empty list is a real answer, and the strongest reason to compute
        this outside the model: asked to compare two weeks, a model will always
        find something to say. Arithmetic is willing to report that nothing
        changed.
        """
        changes: list[dict] = []

        def compare(
            metric: str,
            now: float | None,
            was: float | None,
            lower_is_better: bool = False,
        ) -> None:
            if now is None or was is None:
                return
            if abs(now - was) < MATERIAL_SHIFT * max(abs(was), 1e-9):
                return

            worse = (now > was) if lower_is_better else (now < was)
            changes.append({
                "metric": metric,
                "now": now,
                "usual": was,
                "direction": "worse" if worse else "better",
            })

        compare(
            "adherence_of_asked",
            adherence_of_asked(ledger),
            adherence_of_asked(baseline),
        )
        compare(
            "median_minutes_to_taken",
            median_latency(this_week),
            median_latency(baseline_events),
            lower_is_better=True,
        )

        now_parts = self._by_part_of_day(this_week, tz)
        was_parts = self._by_part_of_day(baseline_events, tz)
        for part in now_parts:
            compare(
                f"{part}_adherence",
                now_parts[part]["adherence_of_asked"],
                was_parts[part]["adherence_of_asked"],
            )

        # Reachability is ours, not hers, so it is reported as its own fact
        # rather than folded into an adherence change she did not cause.
        if ledger.unreachable:
            changes.append({
                "metric": "doses_never_delivered",
                "now": ledger.unreachable,
                "usual": baseline.unreachable,
                "direction": "ours_to_fix",
            })

        return changes


def plain_weekly_note(brief: dict) -> str:
    """The week in English, with no model involved.

    This is what the family sees when the analyst is switched off, slow or
    unavailable — which means the weekly note is a feature of CareBridge rather
    than a feature of Gemini being up. The agent makes this warmer. It is not
    what makes it exist.
    """
    name = brief.get("elder_name") or "She"
    week = brief.get("this_week", {})
    changes = brief.get("what_changed") or []

    if not week.get("scheduled"):
        return f"Nothing was scheduled for {name} this week."

    lines = [
        f"{name} took {week['taken']} of the {week['asked']} doses "
        f"CareBridge was able to ask about."
    ]

    never_delivered = week.get("unreachable", 0)
    if never_delivered:
        lines.append(
            f"{never_delivered} "
            f"{'dose was' if never_delivered == 1 else 'doses were'} never "
            "asked about at all, because no reminder reached the phone."
        )

    on_trust = week.get("taken_on_trust", 0)
    if on_trust:
        lines.append(
            f"{on_trust} of those were recorded by the family rather than "
            f"by {name}."
        )

    worse = [c for c in changes if c["direction"] == "worse"]
    if not worse:
        lines.append("That is much the same as the weeks before.")
    elif any(c["metric"] == "median_minutes_to_taken" for c in worse):
        lines.append("Doses are being taken later than usual.")
    else:
        parts = [c["metric"].replace("_adherence", "") for c in worse]
        lines.append(f"The change is in the {' and '.join(parts)}.")

    return " ".join(lines)
