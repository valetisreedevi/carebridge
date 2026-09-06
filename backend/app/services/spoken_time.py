"""A time said the way a person says it, worked out rather than improvised.

The companion agent used to be handed the bare string "01:30" and nothing else -
no AM/PM, no part of day, no note that it was even 24-hour - and the prompt said
nothing at all about how to phrase a time. So the model invented the wording
fresh every turn, and being a language model it was not consistent: one reply
put the same dose in the afternoon and at night in a single sentence.

Turning 01:30 into "half past one in the morning" is arithmetic. It belongs
here, where it happens the same way every time, and the model's job is reduced
to repeating the sentence it was given.

The boundaries are deliberately the ones the caregiver form already offers when
they pick Morning / Afternoon / Evening / Night, so what the elder hears matches
the button the family actually pressed.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

# Matches SLOTS in frontend/src/components/MedicationForm.tsx.
MORNING_ENDS = 12
AFTERNOON_ENDS = 17
EVENING_ENDS = 20

PARTS: dict[str, dict[str, str]] = {
    "en": {
        "morning": "in the morning",
        "afternoon": "in the afternoon",
        "evening": "in the evening",
        "night": "at night",
    },
    "te": {
        "morning": "ఉదయం",
        "afternoon": "మధ్యాహ్నం",
        "evening": "సాయంత్రం",
        "night": "రాత్రి",
    },
}

# English puts the part of day after the clock, Telugu before it.
TEMPLATES = {"en": "{clock} {part}", "te": "{part} {clock}"}

# What separates the hour from the minutes, and it is not only a typographic
# choice. Read aloud by Google's Telugu voice, a COLON makes the numeral a
# clock time, and the voice then supplies its own part of the day on top of
# ours: "ఉదయం 1:50" is spoken as "ఉదయం అర్ధరాత్రి…" - the same doubling this
# module exists to stop, arriving one layer further down. A dot is read as
# digits and leaves the sentence alone. English has neither the problem nor
# the convention, and keeps its colon.
SEPARATORS = {"en": ":", "te": "."}

FALLBACK = "en"


def part_of_day(hour: int) -> str:
    if hour < MORNING_ENDS:
        return "morning"
    if hour < AFTERNOON_ENDS:
        return "afternoon"
    if hour < EVENING_ENDS:
        return "evening"
    return "night"


def spoken_clock(hour: int, minute: int, separator: str = ":") -> str:
    """13:05 -> 1:05. The part of day carries what am/pm would have said."""
    return f"{hour % 12 or 12}{separator}{minute:02d}"


def say_time(hour: int, minute: int, language: str | None) -> str:
    """One phrase, ready to be repeated verbatim by the model."""
    tongue = language if language in PARTS else FALLBACK
    return TEMPLATES[tongue].format(
        clock=spoken_clock(hour, minute, SEPARATORS[tongue]),
        part=PARTS[tongue][part_of_day(hour)],
    )


def say_moment(moment: datetime, tz: ZoneInfo, language: str | None) -> str:
    """The same, for an instant that still has to be brought into her day."""
    local = moment.astimezone(tz)
    return say_time(local.hour, local.minute, language)
