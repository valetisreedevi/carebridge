"""Whether a medicine is still on the plan for a given day.

A doctor prescribes a course: ten days of an antibiotic, fifteen of a steroid,
three months of something for blood pressure. Until this existed every
medication ran forever, so a five-day course and a lifelong tablet were the
same object and the only way to stop one was for the family to remember, on
day six, to delete it by hand.

Two facts shape everything here:

*   **Dates are the elder's, never the server's.** Nothing in this module
    reads a clock. Callers pass a date they have already computed in the
    elder's timezone, because a course boundary read off a machine in
    us-central1 is wrong for every household that is not in us-central1.

*   **An unreadable date means "keep reminding".** A corrupt or missing field
    degrades to unbounded, never to silence. The cost of one extra reminder is
    an apology; the cost of a missed dose is the thing this product exists to
    prevent.
"""

from datetime import date, timedelta


def _as_date(value: object) -> date | None:
    """The stored value as a date, or None for anything unreadable.

    Dates are written as ISO strings rather than timestamps: Firestore has no
    date type, so a `date` round-trips as a datetime and midnight in Kolkata
    comes back as half past six the previous evening in UTC — the precise
    off-by-one this module exists to prevent.
    """
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def runs_on(medication: dict, local_date: date) -> bool:
    """Whether this medicine should produce doses on the given local day."""
    starts = _as_date(medication.get("starts_on"))
    if starts and local_date < starts:
        return False

    ends = _as_date(medication.get("ends_on"))
    if ends and local_date > ends:
        return False

    return True


def progress(medication: dict, local_date: date) -> dict | None:
    """Day N of M, or None for a medicine with no end in sight.

    Counted in days rather than doses. The doctor said "fifteen days" and the
    calendar has fifteen days on it; "dose 10 of 45" is a number nobody was
    given and nobody can check.
    """
    starts = _as_date(medication.get("starts_on"))
    ends = _as_date(medication.get("ends_on"))
    if not (starts and ends):
        return None

    return {
        "day": (local_date - starts).days + 1,
        "of": (ends - starts).days + 1,
        "ends_on": ends.isoformat(),
        "finished": local_date > ends,
    }


def resolve_window(
    starts_on: date | str | None,
    duration_days: int | None,
    today_local: date,
) -> tuple[str | None, str | None]:
    """The stored (starts_on, ends_on) pair for what the caregiver asked for.

    The end is worked out once, here, and stored — rather than recomputed on
    every read. The guard runs in a per-minute worker across every active
    medication in the system, and one string comparison is cheaper than
    parsing a date and adding to it a few thousand times a day.

    `today_local` is the elder's today, so "for ten days" starting now means
    ten of her days, not ten of the server's.
    """
    # Accepts either what the request carried or what the document already
    # held, so an edit does not have to know which it is looking at.
    given = _as_date(starts_on)

    # Zero and None both mean open-ended. Zero is what the form sends when a
    # caregiver moves a medicine off a course and back to ongoing, which has
    # to be expressible as a value rather than as an absence.
    if not duration_days:
        # A start with no length is legitimate: begin on Monday, carry on
        # until somebody says otherwise.
        return (given.isoformat() if given else None), None

    starts = given or today_local
    # Inclusive of the first day: a three-day course is today, tomorrow and
    # the day after, not four days.
    ends = starts + timedelta(days=duration_days - 1)
    return starts.isoformat(), ends.isoformat()
